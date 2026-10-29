#include <cstdint>
#include <type_traits>
#if __cplusplus < 201703L
#error Build this DPI probe in C++17 mode or newer
#endif
static_assert(sizeof(unsigned int)==4 && sizeof(unsigned long long)==8,"DPI scalar widths");
#define TMA_API extern "C" __declspec(dllexport)
TMA_API unsigned long long tma_dpi_probe(
    unsigned int a, unsigned long long b, unsigned int* out) noexcept {
    *out = a ^ 0xa55aa55aU;
    return b + static_cast<unsigned long long>(a);
}
