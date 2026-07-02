// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

//! Thin C ABI over Anki's shared engine (`anki::backend::Backend`).
//!
//! This mirrors `pylib/rsbridge` (open_backend + command), but exposes a plain
//! C interface so a native iOS/SwiftUI app (and its tests) can drive the exact
//! same engine that desktop uses. Callers never need to know Rust's memory
//! layout: everything crosses the boundary as an opaque handle plus byte
//! buffers. The universal RPC is `Backend::run_service_method`, keyed by the
//! generated `(service, method)` ids.

use std::panic::catch_unwind;
use std::panic::AssertUnwindSafe;
use std::slice;

use anki::backend::init_backend;
use anki::backend::Backend;

/// Build a byte slice from a (possibly null) pointer + length.
///
/// # Safety
/// `ptr` must either be null (any `len`) or point to at least `len`
/// initialised bytes that remain valid for the duration of the call.
unsafe fn slice_from_raw<'a>(ptr: *const u8, len: usize) -> &'a [u8] {
    if ptr.is_null() || len == 0 {
        &[]
    } else {
        slice::from_raw_parts(ptr, len)
    }
}

/// Move `bytes` onto the heap as a boxed slice and transfer ownership to the
/// caller, writing the length to `out_len`. The returned pointer must be
/// released with [`anki_ffi_free`] using that same length. For an empty input
/// the returned pointer is a non-null dangling pointer (safe to pass to
/// [`anki_ffi_free`]); this keeps "null return" reserved for hard failures.
fn buffer_into_raw(bytes: Vec<u8>, out_len: *mut usize) -> *mut u8 {
    let mut boxed = bytes.into_boxed_slice();
    let len = boxed.len();
    let ptr = boxed.as_mut_ptr();
    std::mem::forget(boxed);
    if !out_len.is_null() {
        unsafe { *out_len = len };
    }
    ptr
}

/// Decode the `backend.BackendInit` protobuf in `init_ptr`/`init_len` (empty is
/// allowed and yields defaults: no preferred langs, server=false) and return a
/// heap-allocated [`Backend`] handle. Returns null on error.
#[no_mangle]
#[allow(clippy::not_unsafe_ptr_arg_deref)]
pub extern "C" fn anki_ffi_open(init_ptr: *const u8, init_len: usize) -> *mut Backend {
    let result = catch_unwind(AssertUnwindSafe(|| {
        let init = unsafe { slice_from_raw(init_ptr, init_len) };
        init_backend(init).map(|backend| Box::into_raw(Box::new(backend)))
    }));
    match result {
        Ok(Ok(ptr)) => ptr,
        // decode error or a caught panic
        _ => std::ptr::null_mut(),
    }
}

/// Run a backend RPC identified by `(service, method)` with the protobuf bytes
/// in `in_ptr`/`in_len`.
///
/// On success the response protobuf bytes are returned and `*out_is_err` is set
/// to false. On a backend error the encoded `backend.BackendError` bytes are
/// returned and `*out_is_err` is set to true. `*out_len` always receives the
/// returned buffer's length.
///
/// The returned buffer (when non-null) must be released with [`anki_ffi_free`].
/// A null return indicates a hard failure only (null handle or a caught panic);
/// in that case `*out_len` is 0 and `*out_is_err` is true.
#[no_mangle]
#[allow(clippy::not_unsafe_ptr_arg_deref)]
pub extern "C" fn anki_ffi_run(
    handle: *mut Backend,
    service: u32,
    method: u32,
    in_ptr: *const u8,
    in_len: usize,
    out_len: *mut usize,
    out_is_err: *mut bool,
) -> *mut u8 {
    // Default the out-params to the "hard failure" state; overwritten below.
    if !out_len.is_null() {
        unsafe { *out_len = 0 };
    }
    if !out_is_err.is_null() {
        unsafe { *out_is_err = true };
    }
    if handle.is_null() {
        return std::ptr::null_mut();
    }

    let result = catch_unwind(AssertUnwindSafe(|| {
        let backend = unsafe { &*handle };
        let input = unsafe { slice_from_raw(in_ptr, in_len) };
        backend.run_service_method(service, method, input)
    }));

    match result {
        Ok(Ok(bytes)) => {
            if !out_is_err.is_null() {
                unsafe { *out_is_err = false };
            }
            buffer_into_raw(bytes, out_len)
        }
        // Backend error: bytes are an encoded backend.BackendError; out_is_err
        // is already true from the defaults above.
        Ok(Err(bytes)) => buffer_into_raw(bytes, out_len),
        Err(_) => std::ptr::null_mut(),
    }
}

/// Free a buffer previously returned by [`anki_ffi_run`]. `len` must match the
/// value written to `out_len` for that buffer. A null pointer is ignored.
#[no_mangle]
#[allow(clippy::not_unsafe_ptr_arg_deref)]
pub extern "C" fn anki_ffi_free(ptr: *mut u8, len: usize) {
    if ptr.is_null() {
        return;
    }
    unsafe {
        let slice = std::ptr::slice_from_raw_parts_mut(ptr, len);
        drop(Box::from_raw(slice));
    }
}

/// Drop a [`Backend`] handle previously returned by [`anki_ffi_open`]. A null
/// handle is ignored. The handle must not be used again afterwards.
#[no_mangle]
#[allow(clippy::not_unsafe_ptr_arg_deref)]
pub extern "C" fn anki_ffi_close(handle: *mut Backend) {
    if handle.is_null() {
        return;
    }
    unsafe {
        drop(Box::from_raw(handle));
    }
}

#[cfg(test)]
mod tests {
    use anki_proto::collection::CloseCollectionRequest;
    use anki_proto::collection::OpenCollectionRequest;
    use anki_proto::generic;
    use prost::Message;

    use super::*;

    /// Drive `anki_ffi_run` end to end, returning the response bytes plus the
    /// error flag, and freeing the FFI buffer.
    fn run(handle: *mut Backend, service: u32, method: u32, input: &[u8]) -> (Vec<u8>, bool) {
        let mut out_len: usize = 0;
        let mut out_is_err = false;
        let ptr = anki_ffi_run(
            handle,
            service,
            method,
            input.as_ptr(),
            input.len(),
            &mut out_len,
            &mut out_is_err,
        );
        assert!(!ptr.is_null(), "anki_ffi_run returned null (hard failure)");
        let bytes = unsafe { slice::from_raw_parts(ptr, out_len) }.to_vec();
        anki_ffi_free(ptr, out_len);
        (bytes, out_is_err)
    }

    /// Full C-ABI round trip against the shared engine: open a backend, open a
    /// fresh collection, and confirm the pgrep seam marker comes back.
    #[test]
    fn ffi_roundtrip_open_and_seam_check() {
        let handle = anki_ffi_open(std::ptr::null(), 0);
        assert!(!handle.is_null(), "anki_ffi_open returned null");

        // Open a fresh collection at a temp path (created on open).
        let dir = tempfile::tempdir().unwrap();
        let col_path = dir.path().join("collection.anki2");
        let open_req = OpenCollectionRequest {
            collection_path: col_path.to_string_lossy().into_owned(),
            media_folder_path: String::new(),
            media_db_path: String::new(),
        };
        let (_open_out, is_err) = run(handle, 3, 0, &open_req.encode_to_vec());
        assert!(!is_err, "OpenCollection returned a backend error");

        // PgrepSeamCheck (service 3, method 16): proves the shared engine
        // round-trips through the C ABI.
        let (seam_out, is_err) = run(handle, 3, 16, &[]);
        assert!(!is_err, "PgrepSeamCheck returned a backend error");
        let decoded = generic::String::decode(seam_out.as_slice()).unwrap();
        assert_eq!(decoded.val, "pgrep seam OK (Rust)");

        // Tidy up: close the collection, then drop the backend.
        let close_req = CloseCollectionRequest {
            downgrade_to_schema11: false,
        };
        let (_close_out, is_err) = run(handle, 3, 1, &close_req.encode_to_vec());
        assert!(!is_err, "CloseCollection returned a backend error");

        anki_ffi_close(handle);
    }

    /// Null handle / null buffers must be handled without UB.
    #[test]
    fn null_handle_and_free_are_safe() {
        let mut out_len: usize = 7;
        let mut out_is_err = false;
        let ptr = anki_ffi_run(
            std::ptr::null_mut(),
            3,
            16,
            std::ptr::null(),
            0,
            &mut out_len,
            &mut out_is_err,
        );
        assert!(ptr.is_null());
        assert_eq!(out_len, 0);
        assert!(out_is_err);

        // These must be no-ops rather than crashing.
        anki_ffi_free(std::ptr::null_mut(), 0);
        anki_ffi_close(std::ptr::null_mut());
    }
}
