#pragma once
#include <cstdint>
#include <deque>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

namespace tma {
constexpr std::uint32_t max_beats = 1U << 20;
struct Descriptor {
    std::uint32_t sb, db, rows, cols, srs, scs, drs, dcs;
};
struct Beat { std::uint32_t src, dst, data; };
struct CopyResult {
    std::uint32_t status=0, completed=0;
    std::vector<std::uint32_t> destination, reads;
    std::vector<Beat> writes;
};
struct Failure : std::runtime_error {
    std::uint32_t code;
    Failure(std::uint32_t c,const std::string& message):std::runtime_error(message),code(c){}
};
// Resource/API failures are separate from the DUT's status codes 0..5.
enum Check : std::uint32_t { API=1, UNSEEDED=2, RESOURCE=3, READ_ADDRESS=4,
    READ_DATA=5, WRITE_DATA=6, WRITE_ERROR=7, STATUS=8, PENDING=9,
    MEMORY_DATA=10, READ_COUNT=11, WRITE_COUNT=12, RESPONSE=13 };

std::uint32_t header(const Descriptor&,std::uint32_t src_bytes,std::uint32_t dst_bytes);
CopyResult copy(const Descriptor&,const std::vector<std::uint32_t>& source,
                const std::vector<std::uint32_t>& destination,
                std::int64_t read_fault=-1,std::int64_t write_fault=-1);
std::uint32_t bank(std::uint32_t word,std::uint32_t row_width,bool swizzle,std::uint32_t shift);

class Reference {
    std::uint32_t src_bytes_,dst_bytes_;
    std::unordered_map<std::uint32_t,std::uint32_t> source_,destination_;
    std::uint32_t predicted_status_=0;
    std::size_t read_issued_=0,read_acked_=0,write_issued_=0,write_acked_=0;
    bool active_=false;
public:
    std::vector<Beat> expected;
    std::string diagnostic;
    std::uint64_t calls=0,api_ns=0,predict_ns=0;
    Reference(std::uint32_t src_bytes,std::uint32_t dst_bytes);
    void reset();
    bool bad(bool destination,std::uint32_t address) const;
    void seed(bool destination,std::uint32_t address,std::uint32_t data);
    std::uint32_t memory(bool destination,std::uint32_t address) const;
    void begin(const Descriptor&);
    void cancel() { active_=false; }
    void read_request(std::uint32_t address);
    void read_response(std::uint32_t data,std::uint32_t error);
    void write_request(std::uint32_t address,std::uint32_t data);
    void write_response(std::uint32_t error);
    void finish(std::uint32_t code,std::uint32_t error,std::uint32_t completed);
    void idle() const;
    std::uint32_t status() const { return predicted_status_; }
};
}
