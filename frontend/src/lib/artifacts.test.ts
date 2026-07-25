import { describe, expect, it } from 'vitest'
import { validateArtifactUpload } from '@/lib/artifacts'

describe('artifact upload policy', () => {
  it('accepts CSV/XLSX and rejects other browser uploads', () => {
    expect(validateArtifactUpload(new File(['a,b'], 'DATA.CSV', { type: '' }))).toEqual({ ok: true })
    expect(validateArtifactUpload(new File(['zip'], 'book.xlsx', { type: 'application/octet-stream' }))).toEqual({ ok: true })
    expect(validateArtifactUpload(new File(['x'], 'chart.png', { type: 'image/png' }))).toMatchObject({
      ok: false,
      code: 'unsupported_file_type',
    })
    const tooLarge = new File(['x'], 'large.csv')
    Object.defineProperty(tooLarge, 'size', { value: 50 * 1024 * 1024 + 1 })
    expect(validateArtifactUpload(tooLarge)).toMatchObject({ ok: false, code: 'upload_too_large' })
  })
})
