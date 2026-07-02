// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html
//
// C ABI for Anki's shared engine. This header is what the Swift/Xcode side
// imports (via a module map / bridging header) to drive the same engine that
// desktop uses. It mirrors the Rust surface in rslib/ffi/lib.rs.

#ifndef ANKI_FFI_H
#define ANKI_FFI_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// Opaque handle to an Anki backend (Rust: anki::backend::Backend). Create with
// anki_ffi_open and destroy with anki_ffi_close. Never dereference directly.
typedef struct AnkiBackend AnkiBackend;

// Decode the `backend.BackendInit` protobuf in init_ptr/init_len (passing NULL
// / 0 is allowed and yields defaults) and return a backend handle. Returns
// NULL on error.
AnkiBackend *anki_ffi_open(const uint8_t *init_ptr, size_t init_len);

// Run a backend RPC identified by (service, method) with the request protobuf
// bytes in in_ptr/in_len (NULL / 0 for an empty request).
//
// Returns a heap buffer of length *out_len:
//   *out_is_err == false -> buffer holds the response protobuf bytes.
//   *out_is_err == true  -> buffer holds an encoded `backend.BackendError`.
// The returned buffer (when non-NULL) must be released with anki_ffi_free.
//
// A NULL return indicates a hard failure only (NULL handle or a caught panic);
// in that case *out_len is 0 and *out_is_err is true.
uint8_t *anki_ffi_run(AnkiBackend *handle, uint32_t service, uint32_t method,
                      const uint8_t *in_ptr, size_t in_len, size_t *out_len,
                      bool *out_is_err);

// Free a buffer previously returned by anki_ffi_run. `len` must match the value
// written to *out_len for that buffer. A NULL pointer is ignored.
void anki_ffi_free(uint8_t *ptr, size_t len);

// Drop a backend handle previously returned by anki_ffi_open. A NULL handle is
// ignored. The handle must not be used again afterwards.
void anki_ffi_close(AnkiBackend *handle);

#ifdef __cplusplus
}
#endif

#endif // ANKI_FFI_H
