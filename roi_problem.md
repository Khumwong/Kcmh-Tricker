# ROI OCR Problem Notes

## สิ่งที่ทำงานได้

| ROI | ผล | หมายเหตุ |
|-----|-----|----------|
| mu_rate_roi | ✅ อ่านได้สม่ำเสมอ | font ใหญ่ bold อ่านได้ทุก frame |
| progress_roi | ✅ อ่านได้ส่วนใหญ่ | "17.60%" → 17.6 |
| mu1_roi | ❌ อ่านไม่ได้ | — |
| mu2_roi | ❌ อ่านไม่ได้ | — |

## ปัญหา mu1/mu2

mu1/mu2 แสดงค่าแบบ "4,398.89" / "4,426.65" บน monitor ที่มี moire pattern

สาเหตุที่อ่านไม่ได้:
1. **Font เล็กกว่า mu_rate** — source ROI สูง ~140px แต่ video strip ถูก resize เหลือ 80px (สูญ ~42%)
2. **Moire pattern** จากกล้องถ่าย monitor โดยตรง ทำให้ diagonal stripes รบกวนจนมองเหมือนตัวอักษร
3. OCR อ่านเป็น 'E', 'I', 'Eicd' แทนตัวเลข

## สิ่งที่ลองแล้วไม่ได้ผล
- 2x / 4x upscale
- HSV saturation extraction (white text = low S, high V)
- Binary threshold (grayscale > 150 หรือ > 180)
- Dilation 1-2 iterations
- Image inversion
- pytesseract + EasyOCR หลาย PSM mode
- CROP_H เพิ่มจาก 80 → 120 → 250px

## วิธีแก้ที่ยังไม่ได้ทำ
- กล้องที่ 2 ชี้เฉพาะ mu1/mu2 area ให้ font ใหญ่พอ
- Optical zoom เข้าไปที่ตัวเลขโดยตรง (ไม่ใช่ digital zoom)
- ถามว่า beam delivery system export log ออกมาได้ไหม

## Config ปัจจุบัน (ใช้งานได้)
- `CROP_H = 80`, `CROP_W = 320`
- ROI_NAMES: `['mu1_roi', 'mu2_roi', 'mu_rate_roi', 'progress_roi']`
- mu1/mu2 ใช้ scale=4x, rate/progress ใช้ scale=2x
- mu_rate: validate range 10,000–300,000 (fallback /10 สำหรับ decimal drop)
- progress: validate range 0–100
