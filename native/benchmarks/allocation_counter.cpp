#include "allocation_counter.hpp"

#include <atomic>
#include <cstdlib>
#include <new>
#include <thread>
#if defined(_WIN32)
#include <malloc.h>
#endif

namespace {
std::atomic<std::uint64_t> calls{0};
thread_local bool tracking = false;
void counted() noexcept { if (tracking) { calls.fetch_add(1, std::memory_order_relaxed); } }
void* ordinary(std::size_t size) {
    void* pointer = std::malloc(size == 0 ? 1 : size);
    if (!pointer) { throw std::bad_alloc(); }
    counted();
    return pointer;
}
void* aligned(std::size_t size, std::size_t alignment) {
    void* pointer = nullptr;
#if defined(_WIN32)
    pointer = _aligned_malloc(size == 0 ? 1 : size, alignment);
#else
    if (::posix_memalign(&pointer, alignment, size == 0 ? 1 : size) != 0) { pointer = nullptr; }
#endif
    if (!pointer) { throw std::bad_alloc(); }
    counted();
    return pointer;
}
void aligned_free(void* pointer) noexcept {
#if defined(_WIN32)
    _aligned_free(pointer);
#else
    std::free(pointer);
#endif
}
}

namespace etf_genome::benchmark {
void reset_allocations() noexcept { calls.store(0, std::memory_order_relaxed); }
std::uint64_t allocations() noexcept { return calls.load(std::memory_order_relaxed); }
AllocationScope::AllocationScope(bool enabled) noexcept : previous_(tracking) { tracking = enabled; }
AllocationScope::~AllocationScope() { tracking = previous_; }
}

void* operator new(std::size_t size) { return ordinary(size); }
void* operator new[](std::size_t size) { return ordinary(size); }
void* operator new(std::size_t size, const std::nothrow_t&) noexcept {
    try { return ordinary(size); } catch (const std::bad_alloc&) { return nullptr; }
}
void* operator new[](std::size_t size, const std::nothrow_t&) noexcept {
    try { return ordinary(size); } catch (const std::bad_alloc&) { return nullptr; }
}
void operator delete(void* pointer) noexcept { std::free(pointer); }
void operator delete[](void* pointer) noexcept { std::free(pointer); }
void operator delete(void* pointer, std::size_t) noexcept { std::free(pointer); }
void operator delete[](void* pointer, std::size_t) noexcept { std::free(pointer); }
void operator delete(void* pointer, const std::nothrow_t&) noexcept { std::free(pointer); }
void operator delete[](void* pointer, const std::nothrow_t&) noexcept { std::free(pointer); }
void* operator new(std::size_t size, std::align_val_t align) { return aligned(size, static_cast<std::size_t>(align)); }
void* operator new[](std::size_t size, std::align_val_t align) { return aligned(size, static_cast<std::size_t>(align)); }
void* operator new(std::size_t size, std::align_val_t align, const std::nothrow_t&) noexcept {
    try { return aligned(size, static_cast<std::size_t>(align)); }
    catch (const std::bad_alloc&) { return nullptr; }
}
void* operator new[](std::size_t size, std::align_val_t align, const std::nothrow_t&) noexcept {
    try { return aligned(size, static_cast<std::size_t>(align)); }
    catch (const std::bad_alloc&) { return nullptr; }
}
void operator delete(void* pointer, std::align_val_t) noexcept { aligned_free(pointer); }
void operator delete[](void* pointer, std::align_val_t) noexcept { aligned_free(pointer); }
void operator delete(void* pointer, std::size_t, std::align_val_t) noexcept { aligned_free(pointer); }
void operator delete[](void* pointer, std::size_t, std::align_val_t) noexcept { aligned_free(pointer); }
void operator delete(void* pointer, std::align_val_t, const std::nothrow_t&) noexcept { aligned_free(pointer); }
void operator delete[](void* pointer, std::align_val_t, const std::nothrow_t&) noexcept { aligned_free(pointer); }

namespace etf_genome::benchmark {
namespace {
// Volatile function pointers force real calls to the replacement functions.
// The compiler cannot apply permitted new-expression allocation elision here.
void explicit_scalar_allocation() {
    using Allocate = void* (*)(std::size_t);
    using Deallocate = void (*)(void*) noexcept;
    Allocate volatile allocate = static_cast<Allocate>(&::operator new);
    Deallocate volatile release = static_cast<Deallocate>(&::operator delete);
    void* pointer = allocate(17);
    *static_cast<volatile unsigned char*>(pointer) = 42;
    release(pointer);
}

void explicit_allocation_variants() {
    using Allocate = void* (*)(std::size_t);
    using AlignedAllocate = void* (*)(std::size_t, std::align_val_t);
    using NothrowAllocate = void* (*)(std::size_t, const std::nothrow_t&) noexcept;
    using AlignedNothrowAllocate = void* (*)(std::size_t, std::align_val_t,
                                           const std::nothrow_t&) noexcept;
    using Deallocate = void (*)(void*) noexcept;
    using AlignedDeallocate = void (*)(void*, std::align_val_t) noexcept;
    Allocate volatile scalar = static_cast<Allocate>(&::operator new);
    Allocate volatile array = static_cast<Allocate>(&::operator new[]);
    AlignedAllocate volatile aligned_scalar = static_cast<AlignedAllocate>(&::operator new);
    AlignedAllocate volatile aligned_array = static_cast<AlignedAllocate>(&::operator new[]);
    NothrowAllocate volatile scalar_nothrow = static_cast<NothrowAllocate>(&::operator new);
    NothrowAllocate volatile array_nothrow = static_cast<NothrowAllocate>(&::operator new[]);
    AlignedNothrowAllocate volatile aligned_scalar_nothrow =
        static_cast<AlignedNothrowAllocate>(&::operator new);
    AlignedNothrowAllocate volatile aligned_array_nothrow =
        static_cast<AlignedNothrowAllocate>(&::operator new[]);
    Deallocate volatile free_scalar = static_cast<Deallocate>(&::operator delete);
    Deallocate volatile free_array = static_cast<Deallocate>(&::operator delete[]);
    AlignedDeallocate volatile free_aligned_scalar = static_cast<AlignedDeallocate>(&::operator delete);
    AlignedDeallocate volatile free_aligned_array = static_cast<AlignedDeallocate>(&::operator delete[]);
    constexpr auto alignment = std::align_val_t{64};
    void* pointer = scalar(17); free_scalar(pointer);
    pointer = array(17); free_array(pointer);
    pointer = aligned_scalar(17, alignment); free_aligned_scalar(pointer, alignment);
    pointer = aligned_array(17, alignment); free_aligned_array(pointer, alignment);
    pointer = scalar_nothrow(17, std::nothrow);
    if (!pointer) { throw std::bad_alloc(); }
    free_scalar(pointer);
    pointer = array_nothrow(17, std::nothrow);
    if (!pointer) { throw std::bad_alloc(); }
    free_array(pointer);
    pointer = aligned_scalar_nothrow(17, alignment, std::nothrow);
    if (!pointer) { throw std::bad_alloc(); }
    free_aligned_scalar(pointer, alignment);
    pointer = aligned_array_nothrow(17, alignment, std::nothrow);
    if (!pointer) { throw std::bad_alloc(); }
    free_aligned_array(pointer, alignment);
}
} // namespace

AllocationSelfCheck allocation_counter_self_check() {
    AllocationScope inactive(false);
    reset_allocations();
    explicit_scalar_allocation(); // No active scope: not counted.
    {
        AllocationScope active(true);
        explicit_allocation_variants(); // Eight distinct replacement entry points.
        {
            AllocationScope suspended(false);
            explicit_scalar_allocation();
        }
    }
    std::jthread thread([] {
        explicit_scalar_allocation(); // New thread begins untracked.
        AllocationScope active(true);
        explicit_scalar_allocation(); // Exactly one tracked call on this thread.
    });
    thread.join();
    {
        AllocationScope active(true);
        explicit_scalar_allocation();
        { AllocationScope suspended(false); explicit_scalar_allocation(); }
        explicit_scalar_allocation(); // Nested scope restored the outer true state.
    }
    return {allocations(), 11};
}
} // namespace etf_genome::benchmark
