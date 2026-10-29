#include "tma_reference.hpp"
#include <chrono>
#include <memory>
#ifdef _WIN32
#define TMA_API extern "C" __declspec(dllexport)
#include <windows.h>
#include <psapi.h>
#else
#define TMA_API extern "C"
#include <sys/resource.h>
#endif

namespace {
std::string creation_error;
using Clock=std::chrono::steady_clock;
template<class F> unsigned int guard(void* handle,F function) noexcept {
    if(!handle) return tma::API;
    auto& r=*static_cast<tma::Reference*>(handle);const auto start=Clock::now();++r.calls;
    unsigned int code=0;
    try {function(r);r.diagnostic.clear();}
    catch(const tma::Failure& e) {code=e.code;r.diagnostic=e.what();}
    catch(const std::exception& e) {code=tma::API;r.diagnostic=e.what();}
    catch(...) {code=tma::API;r.diagnostic="Unknown C++ exception";}
    r.api_ns+=std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now()-start).count();return code;
}
}
TMA_API void* tma_ref_create(unsigned int src,unsigned int dst) noexcept {
    try {creation_error.clear();return new tma::Reference(src,dst);}
    catch(const std::exception& e){creation_error=e.what();return nullptr;}
    catch(...){creation_error="Reference construction failed";return nullptr;}
}
TMA_API void tma_ref_destroy(void* h) noexcept {delete static_cast<tma::Reference*>(h);}
TMA_API const char* tma_ref_error(void* h) noexcept {
    return h?static_cast<tma::Reference*>(h)->diagnostic.c_str():creation_error.c_str();
}
TMA_API unsigned int tma_ref_reset(void* h) noexcept {return guard(h,[](auto& r){r.reset();});}
TMA_API unsigned int tma_ref_seed(void* h,unsigned int dst,unsigned int addr,unsigned int data) noexcept {
    return guard(h,[&](auto& r){if(dst>1)throw tma::Failure(tma::API,"Invalid memory endpoint");r.seed(dst!=0,addr,data);});
}
TMA_API unsigned int tma_ref_read(void* h,unsigned int dst,unsigned int addr,unsigned int* data) noexcept {
    return guard(h,[&](auto& r){if(!data||dst>1)throw tma::Failure(tma::API,"Invalid output or endpoint");*data=r.memory(dst!=0,addr);});
}
TMA_API unsigned int tma_ref_begin(void* h,unsigned int sb,unsigned int db,unsigned int rows,unsigned int cols,
                                  unsigned int srs,unsigned int scs,unsigned int drs,unsigned int dcs) noexcept {
    return guard(h,[&](auto& r){r.begin({sb,db,rows,cols,srs,scs,drs,dcs});});
}
TMA_API unsigned int tma_ref_beat(void* h,unsigned int index,unsigned int* src,unsigned int* dst,unsigned int* data) noexcept {
    return guard(h,[&](auto& r){if(!src||!dst||!data||index>=r.expected.size())throw tma::Failure(tma::API,"Invalid expected-beat index/output");
        const auto& b=r.expected[index];*src=b.src;*dst=b.dst;*data=b.data;});
}
// Prediction-only benchmark path: preserve initialized memory, end the
// reference transaction, and leave expected beats available for readback.
TMA_API unsigned int tma_ref_prediction(void* h,unsigned int sb,unsigned int db,unsigned int rows,unsigned int cols,
                                       unsigned int srs,unsigned int scs,unsigned int drs,unsigned int dcs) noexcept {
    return guard(h,[&](auto& r){r.begin({sb,db,rows,cols,srs,scs,drs,dcs});r.cancel();});
}
TMA_API unsigned int tma_ref_event(void* h,unsigned int kind,unsigned int addr,unsigned int data,
                                  unsigned int error,unsigned int count,unsigned int code) noexcept {
    return guard(h,[&](auto& r){switch(kind) {
        case 0:r.read_request(addr);break;case 1:r.read_response(data,error);break;
        case 2:r.write_request(addr,data);break;case 3:r.write_response(error);break;
        case 4:r.finish(code,error,count);break;case 5:r.idle();break;
        default:throw tma::Failure(tma::API,"Invalid observation kind");
    }});
}
TMA_API unsigned long long tma_ref_clock_ns() noexcept {
    return static_cast<unsigned long long>(std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now().time_since_epoch()).count());
}
TMA_API unsigned long long tma_ref_peak_bytes() noexcept {
#ifdef _WIN32
    PROCESS_MEMORY_COUNTERS counters{};
    return GetProcessMemoryInfo(GetCurrentProcess(),&counters,sizeof(counters))?counters.PeakWorkingSetSize:0;
#else
    rusage usage{};return getrusage(RUSAGE_SELF,&usage)==0?static_cast<unsigned long long>(usage.ru_maxrss)*1024:0;
#endif
}
TMA_API unsigned long long tma_ref_metric(void* h,unsigned int which) noexcept {
    if(!h)return 0;
    const auto& r=*static_cast<tma::Reference*>(h);
    switch(which){case 0:return r.calls;case 1:return r.api_ns;case 2:return r.predict_ns;
        case 3:return r.expected.size();case 4:return r.status();default:return 0;}
}
TMA_API unsigned int tma_ref_noop(unsigned int value) noexcept {return value^0xa55aa55aU;}
