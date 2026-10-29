#include "tma_reference.hpp"
#include <algorithm>
#include <chrono>
#include <fstream>
#include <iostream>
#include <numeric>
extern "C" unsigned long long tma_ref_peak_bytes() noexcept;
extern "C" unsigned int tma_ref_noop(unsigned int) noexcept;
namespace {
void check(bool pass,const char* name) {if(!pass)throw std::runtime_error(name);}
void selftest() {
    std::vector<std::uint32_t> source(64),initial(64,0xcafe);
    std::iota(source.begin(),source.end(),0);
    tma::Descriptor d{0,0,2,3,6,2,6,2};
    auto run=[&](tma::Descriptor x,std::int64_t rf=-1,std::int64_t wf=-1){return tma::copy(x,source,initial,rf,wf);};
    auto x=d;x.rows=x.cols=1;check(run(x).completed==1,"1x1");
    auto r=run(d);check(r.completed==6 && r.destination[5]==5 && r.destination[6]==0xcafe,"rectangle and guards");
    x=d;x.drs=2;x.dcs=4;r=run(x);
    check(std::vector<std::uint32_t>(r.destination.begin(),r.destination.begin()+6)==std::vector<std::uint32_t>({0,3,1,4,2,5}),"transpose");
    x=d;x.srs=8;x.drs=12;r=run(x);check(r.destination[6]==4 && r.destination[3]==0xcafe,"padded rows");
    x=d;x.sb=2;x.srs=x.scs=0;r=run(x);check(r.destination[5]==1,"broadcast");
    x=d;x.rows=1;x.cols=2;x.sb=126;x.srs=0;r=run(x);check(r.status==3 && r.completed==1 && r.destination[0]==63,"late bounds");
    x=d;x.rows=0;x.sb=1;check(run(x).status==1,"empty priority");
    x=d;x.srs=1;check(run(x).status==2,"unused-stride alignment");
    x=d;x.sb=128;check(run(x).status==3 && run(x).reads.empty(),"initial bounds");
    x=d;x.drs=x.dcs=0;check(run(x).destination[0]==5,"ordered repeated destination");
    r=run(d,2);check(r.status==4 && r.completed==2 && r.reads.size()==3 && r.writes.size()==2,"read fault prefix");
    r=run(d,-1,2);check(r.status==5 && r.completed==2 && r.writes.size()==3 && r.destination[2]==0xcafe,"write fault prefix");
    bool rejected=false;try{auto invalid=source;invalid[0]=65536;tma::copy(d,invalid,initial);}catch(const tma::Failure&){rejected=true;}
    check(rejected,"16-bit data validation");
    rejected=false;try{x=d;x.rows=65536;run(x);}catch(const tma::Failure&){rejected=true;}check(rejected,"count width");
    rejected=false;try{x=d;x.rows=2048;x.cols=1024;x.srs=x.scs=x.drs=x.dcs=0;run(x);}catch(const tma::Failure& e){rejected=e.code==tma::RESOURCE;}
    check(rejected,"bounded allocations");
    tma::Reference model(128,128),other(128,128);
    rejected=false;try{model.memory(false,0);}catch(const tma::Failure&){rejected=true;}check(rejected,"unseeded memory");
    for(unsigned i=0;i<6;++i)model.seed(false,i*2,i);
    model.begin(d);
    for(unsigned i=0;i<6;++i){model.read_request(i*2);model.read_response(i,0);model.write_request(i*2,i);model.write_response(0);}
    model.finish(0,0,6);model.idle();check(model.memory(true,10)==5,"transaction commits");
    model.reset();rejected=false;try{model.memory(true,10);}catch(const tma::Failure&){rejected=true;}check(rejected,"reset state");
    model.seed(false,0,123);other.seed(false,0,456);check(model.memory(false,0)==123 && other.memory(false,0)==456,"handle isolation");
    x=d;x.rows=x.cols=1;model.begin(x);model.read_request(0);
    rejected=false;try{model.read_response(124,0);}catch(const tma::Failure& e){rejected=e.code==tma::READ_DATA;}check(rejected,"data checker");
    check(tma::bank(32,10,true,5)==1 && tma::bank(32,10,false,5)==0,"bank mapping");
    std::cout<<"CPP_SELFTEST_PASS cases=21\n";
}
void array(std::ostream& out,const std::vector<std::uint32_t>& values) {
    out<<'[';bool comma=false;for(auto v:values){if(comma)out<<',';out<<v;comma=true;}out<<']';
}
void vectors(const char* input,const char* output) {
    std::ifstream in(input);std::ofstream out(output);check(bool(in)&&bool(out),"vector files");
    unsigned cases;in>>cases;check(cases<=10000,"too many vector cases");
    for(unsigned n=0;n<cases;++n){
        tma::Descriptor d{};unsigned ns=0,nd=0;std::int64_t rf=-1,wf=-1;
        in>>d.sb>>d.db>>d.rows>>d.cols>>d.srs>>d.scs>>d.drs>>d.dcs>>ns>>nd>>rf>>wf;
        check(ns<=tma::max_beats && nd<=tma::max_beats,"vector allocation limit");
        std::vector<std::uint32_t> source(ns),destination(nd);for(auto& v:source)in>>v;for(auto& v:destination)in>>v;
        check(bool(in),"truncated vectors");auto r=tma::copy(d,source,destination,rf,wf);
        out<<"{\"status\":"<<r.status<<",\"completed\":"<<r.completed<<",\"reads\":";array(out,r.reads);
        out<<",\"writes\":[";bool comma=false;for(const auto& b:r.writes){if(comma)out<<',';out<<'['<<b.dst<<','<<b.data<<']';comma=true;}
        out<<"],\"destination\":";array(out,r.destination);out<<"}\n";
    }
    std::cout<<"CPP_VECTORS_PASS cases="<<cases<<'\n';
}
void benchmark() {
    using Clock=std::chrono::steady_clock;
    for(unsigned side:{1U,8U,16U,32U,64U,128U}) {
        const unsigned words=std::max(4096U,side*side),loops=std::max(2U,std::min(100U,100000U/(side*side)));
        std::vector<std::uint32_t> source(words),initial(words);
        for(unsigned i=0;i<words;++i){source[i]=(i*73^0xa55a)&65535;initial[i]=(i^0xca71)&65535;}
        tma::Descriptor d{0,0,side,side,side*2,2,2,side*2};
        for(int warm=0;warm<3;++warm)tma::copy(d,source,initial);
        std::uint64_t checksum=0;
        std::cout<<"{\"side\":"<<side<<",\"elements\":"<<side*side<<",\"loops\":"<<loops<<",\"ns_per_descriptor\":[";
        for(int repeat=0;repeat<7;++repeat){
            const auto start=Clock::now();
            for(unsigned i=0;i<loops;++i){auto r=tma::copy(d,source,initial);checksum+=r.completed+r.destination.back();}
            const auto ns=std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now()-start).count();
            if(repeat)std::cout<<',';
            std::cout<<double(ns)/loops;
        }
        std::cout<<"],\"process_peak_bytes\":"<<tma_ref_peak_bytes()<<",\"checksum\":"<<checksum<<"}\n";
    }
}
void prediction_benchmark() {
    using Clock=std::chrono::steady_clock;
    tma::Reference model(67108864,8192);
    for(unsigned i=0;i<4096;++i)model.seed(false,i*2,(i*73^0xa55a)&65535);
    for(unsigned side:{1U,8U,16U,32U,64U}) {
        const unsigned loops=100;
        tma::Descriptor d{0,0,side,side,side*2,2,2,side*2};
        for(int warm=0;warm<3;++warm){model.begin(d);model.cancel();}
        std::cout<<"{\"side\":"<<side<<",\"elements\":"<<side*side<<",\"loops\":"<<loops<<",\"ns_per_descriptor\":[";
        for(int repeat=0;repeat<7;++repeat){
            const auto start=Clock::now();
            for(unsigned i=0;i<loops;++i){model.begin(d);model.cancel();}
            const auto ns=std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now()-start).count();
            if(repeat)std::cout<<',';
            std::cout<<double(ns)/loops;
        }
        check(model.expected.size()==side*side,"prediction size");
        std::cout<<"],\"process_peak_bytes\":"<<tma_ref_peak_bytes()<<"}\n";
    }
    unsigned checksum=0;const auto start=Clock::now();
    for(unsigned i=0;i<1000000;++i)checksum=((checksum<<1)|(checksum>>31))^tma_ref_noop(i);
    std::cerr<<"NATIVE_NOOP_NS_PER_CALL="<<double(std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now()-start).count())/1000000
             <<" checksum="<<checksum<<'\n';
}
}
int main(int argc,char** argv) {
    try {
        check(argc>=2,"Expected selftest, vectors, benchmark or banks");const std::string mode=argv[1];
        if(mode=="selftest") selftest();
        else if(mode=="vectors"){check(argc==4,"Expected input/output paths");vectors(argv[2],argv[3]);}
        else if(mode=="benchmark")benchmark();
        else if(mode=="prediction")prediction_benchmark();
        else if(mode=="banks"){for(unsigned swizzle=0;swizzle<2;++swizzle)for(unsigned word=0;word<4096;++word)std::cout<<tma::bank(word,10,swizzle!=0,5)<<'\n';}
        else throw std::runtime_error("Unknown mode");
        return 0;
    }catch(const std::exception& e){std::cerr<<"CPP_REFERENCE_ERROR: "<<e.what()<<'\n';return 1;}
}
