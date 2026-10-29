#include "tma_reference.hpp"
#include <algorithm>
#include <chrono>
#include <limits>
#if __cplusplus < 201703L
#error This reference model requires C++17 or newer
#endif

namespace tma {
namespace {
void require(bool condition,std::uint32_t code,const char* message) {
    if(!condition) throw Failure(code,message);
}
void descriptor(const Descriptor& d) {
    require(d.rows<=65535 && d.cols<=65535,API,"Descriptor counts exceed 16 bits");
}
void capacity(std::uint32_t bytes) {
    require(bytes>=2 && !(bytes&1) && bytes<=67108864,API,"Endpoint capacity must be even, 2..64 MiB");
}
template<class F> std::uint32_t coordinates(const Descriptor& d,std::uint32_t sb,std::uint32_t db,F visit) {
    std::uint32_t index=0;
    for(std::uint32_t row=0;row<d.rows;++row) for(std::uint32_t col=0;col<d.cols;++col) {
        const std::uint64_t source=std::uint64_t(d.sb)+std::uint64_t(row)*d.srs+std::uint64_t(col)*d.scs;
        const std::uint64_t destination=std::uint64_t(d.db)+std::uint64_t(row)*d.drs+std::uint64_t(col)*d.dcs;
        if(source>=sb || destination>=db) return 3;
        require(index<max_beats,RESOURCE,"Reference beat limit exceeded; no DUT status is fabricated");
        const auto code=visit(index++,std::uint32_t(source),std::uint32_t(destination));
        if(code) return code;
    }
    return 0;
}
}
std::uint32_t header(const Descriptor& d,std::uint32_t src,std::uint32_t dst) {
    descriptor(d);capacity(src);capacity(dst);
    if(!d.rows || !d.cols) return 1;
    if((d.sb|d.db|d.srs|d.scs|d.drs|d.dcs)&1) return 2;
    if(d.sb>src-2 || d.srs>src-2 || d.scs>src-2 || d.db>dst-2 || d.drs>dst-2 || d.dcs>dst-2) return 3;
    return 0;
}
CopyResult copy(const Descriptor& d,const std::vector<std::uint32_t>& source,
                const std::vector<std::uint32_t>& destination,std::int64_t rf,std::int64_t wf) {
    require(source.size()<=33554432 && destination.size()<=33554432,RESOURCE,"Endpoint size exceeds 64 MiB");
    require(rf>=-1 && wf>=-1,API,"Fault index must be -1 or nonnegative");
    for(auto value:source) require(value<=65535,API,"Source data exceeds 16 bits");
    for(auto value:destination) require(value<=65535,API,"Destination data exceeds 16 bits");
    CopyResult result;result.destination=destination;
    result.status=header(d,std::uint32_t(source.size()*2),std::uint32_t(destination.size()*2));
    if(result.status) return result;
    result.status=coordinates(d,std::uint32_t(source.size()*2),std::uint32_t(destination.size()*2),
        [&](std::uint32_t index,std::uint32_t sa,std::uint32_t da)->std::uint32_t {
            result.reads.push_back(sa);
            if(index==rf) return 4;
            const auto data=source[sa/2];
            result.writes.push_back({sa,da,data});
            if(index==wf) return 5;
            result.destination[da/2]=data;++result.completed;return 0;
        });
    return result;
}
std::uint32_t bank(std::uint32_t word,std::uint32_t width,bool swizzle,std::uint32_t shift) {
    require(width>=1 && width<=20 && (!swizzle || (shift>=2 && shift<=width)),API,"Invalid bank-layout configuration");
    require(word<(4U<<width),API,"Logical scratchpad word out of range");
    return (word&3U)^(swizzle ? ((word>>shift)&3U):0U);
}
Reference::Reference(std::uint32_t src,std::uint32_t dst):src_bytes_(src),dst_bytes_(dst) {
    capacity(src);capacity(dst);
}
void Reference::reset() {
    source_.clear();destination_.clear();expected.clear();active_=false;predicted_status_=0;
    read_issued_=read_acked_=write_issued_=write_acked_=0;
}
bool Reference::bad(bool destination,std::uint32_t addr) const {
    return (addr&1) || addr>=(destination?dst_bytes_:src_bytes_);
}
void Reference::seed(bool destination,std::uint32_t addr,std::uint32_t data) {
    require(!bad(destination,addr) && data<=65535,API,"Invalid acknowledged memory write");
    auto& map=destination?destination_:source_;
    require(map.size()<max_beats || map.count(addr/2),RESOURCE,"Reference initialized-word limit exceeded");
    map[addr/2]=data;
}
std::uint32_t Reference::memory(bool destination,std::uint32_t addr) const {
    require(!bad(destination,addr),API,"Invalid memory lookup");
    const auto& map=destination?destination_:source_;const auto it=map.find(addr/2);
    require(it!=map.end(),UNSEEDED,"Reference read of unseeded memory");return it->second;
}
void Reference::begin(const Descriptor& d) {
    require(!active_,PENDING,"Descriptor accepted with unfinished work");
    const auto start=std::chrono::steady_clock::now();
    expected.clear();read_issued_=read_acked_=write_issued_=write_acked_=0;
    predicted_status_=header(d,src_bytes_,dst_bytes_);
    if(!predicted_status_) predicted_status_=coordinates(d,src_bytes_,dst_bytes_,
        [&](std::uint32_t,std::uint32_t sa,std::uint32_t da)->std::uint32_t {
            expected.push_back({sa,da,memory(false,sa)});return 0;
        });
    active_=true;
    predict_ns+=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-start).count();
}
void Reference::read_request(std::uint32_t addr) {
    require(active_ && read_issued_<expected.size(),READ_COUNT,"Unexpected DMA read request");
    require(addr==expected[read_issued_].src,READ_ADDRESS,"DMA read address differs from mathematical prediction");
    ++read_issued_;
}
void Reference::read_response(std::uint32_t data,std::uint32_t error) {
    require(read_acked_<read_issued_,RESPONSE,"DMA read response without a request");
    require(!error && data==expected[read_acked_].data,READ_DATA,"DMA read data/error differs from reference");++read_acked_;
}
void Reference::write_request(std::uint32_t addr,std::uint32_t data) {
    require(active_ && write_issued_<expected.size(),WRITE_COUNT,"Unexpected DMA write request");
    const auto& beat=expected[write_issued_];
    require(write_issued_<read_acked_ && addr==beat.dst && data==beat.data,WRITE_DATA,"DMA write address/data/order differs from reference");
    ++write_issued_;
}
void Reference::write_response(std::uint32_t error) {
    require(write_acked_<write_issued_,RESPONSE,"DMA write response without a request");
    require(!error,WRITE_ERROR,"Legal scratchpad write returned an error");
    const auto& beat=expected[write_acked_++];seed(true,beat.dst,beat.data);
}
void Reference::finish(std::uint32_t code,std::uint32_t error,std::uint32_t completed) {
    require(active_ && code==predicted_status_ && error==std::uint32_t(predicted_status_!=0) && completed==expected.size(),STATUS,"Completion status/count differs from reference");
    require(read_issued_==expected.size() && read_acked_==expected.size() && write_issued_==expected.size() && write_acked_==expected.size(),PENDING,"Completion before expected read/write prefix drained");
    active_=false;
}
void Reference::idle() const {require(!active_,PENDING,"Reference has an unfinished descriptor");}
}
