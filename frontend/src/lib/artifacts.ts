export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024

export type UploadValidation =
  | { ok: true }
  | { ok: false; code: 'upload_too_large' | 'unsupported_file_type'; message: string }

export function validateArtifactUpload(file: File): UploadValidation {
  const extension = file.name.toLowerCase().split('.').pop()
  if (extension !== 'csv' && extension !== 'xlsx') {
    return {
      ok: false,
      code: 'unsupported_file_type',
      message: 'Only CSV and XLSX files are supported.',
    }
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return {
      ok: false,
      code: 'upload_too_large',
      message: 'The file exceeds the 50 MiB upload limit.',
    }
  }
  return { ok: true }
}
