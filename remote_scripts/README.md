# remote_scripts/ — server-side processing scripts

ทุกไฟล์ `*.py` / `*.md` ในโฟลเดอร์นี้ถูก `RsyncManager` ส่งขึ้น server ไปไว้ที่
`<remote_path>/scripts/` อัตโนมัติตอนกด connect rsync ใน GUI
(ดู [`modules/rsync_manager.py`](../modules/rsync_manager.py) `_do_connect`).

เพิ่มสคริปต์ server ตัวใหม่ = วางไฟล์ `.py` ในโฟลเดอร์นี้ พอ ไม่ต้องแก้โค้ดที่อื่น

Python บน server: `~/sutpct-env/bin/python3` (มี pyeudaq, uproot, easyocr, torch, psutil)

Layout ปลายทางบน server:

```
<remote_path>/
├── raw/      run*.raw            ← rsync จาก GUI
├── root/     run*.root           ← StdEventMonitor_faster (C++) หรือ _fast.py สร้าง
├── log/      run*.log            ← program log + tee ของ conversion
├── gating/   run*_gating.csv     ← \xFE/\xEF + Zaber position จาก GUI
├── video/    mu_video_*.mp4      ← scp จาก GUI
└── scripts/  ← โฟลเดอร์นี้ทั้งหมด
```

---

## 1. `StdEventMonitor_faster.cpp` (+ `build_monitor.sh`) — raw → ROOT (ตัวหลัก)

C++ port ของ `StdEventMonitor_fast.py` — อ่าน raw ครั้งเดียว, trigger-sync
reassignment สูตรเดียวกัน, เขียน ROOT object แท้ผ่าน TFile. output เป็น **superset**
ของตัว Python: histogram เดิมครบ + เพิ่ม `EUDAQ Monitor/Hits vs TimeStamp`
(bin 10 ms) และทั้ง dir `Alignment/` (Gaussian fit ต่อ sensor, beam center vs Z,
linear fit, beam offset/angle ที่ collimator).

```bash
# build (auto: run_with_stats.py เรียกให้เองถ้า binary หาย/เก่ากว่า .cpp)
bash build_monitor.sh              # หรือ --force
# run
./StdEventMonitor_faster <raw_file> [-o <output.root>]
```

`build_monitor.sh` ต้องการ C++17 compiler + ROOT (`root-config`) + EUDAQ2 build.
ปรับ path ผ่าน env: `EUDAQ_PREFIX` (ดีฟอลต์ `/home/sutpct/eudaq2`), `EUDAQ_INC`,
`EUDAQ_LIB`, `CXX`, หรือ `MONITOR_BUILD_CMD` (คำสั่ง compile เต็มๆ ถ้า auto-probe พลาด).

⚠️ ค่าคงที่ geometry ใน `Alignment/` ฝังในโค้ด (`kFirstSensorZmm=112`, spacing 25 mm,
pitch 0.02924/0.02688, collimator z=−60 mm) — ถ้าไม่ตรง setup KCMH กราฟ alignment
จะมั่ว (histogram อื่นไม่กระทบ). compile flag `STDEVENTMONITOR_EUDAQ_COMPATIBLE`
สลับไปโหมด collector-EventN + TProfile; **ดีฟอลต์ = trigger-sync = ตรงกับตัว Python**.

## 2. `StdEventMonitor_fast.py` — raw → ROOT (fallback)

ตัว Python เดิม (ขนานด้วย `mp.Pool`). ยังใช้เป็น fallback อัตโนมัติเมื่อ build C++ ไม่ผ่าน.

```bash
~/sutpct-env/bin/python3 StdEventMonitor_fast.py <raw_file> -o <output.root>
```

| อาร์กิวเมนต์ | ความหมาย |
|---|---|
| `raw_file` | ไฟล์ `.raw` อินพุต (บังคับ) |
| `-o, --output` | ROOT เอาต์พุต (ดีฟอลต์: เปลี่ยนนามสกุล `.raw` → `.root`) |
| `--nplanes N` | จำนวน plane เริ่มต้น (ดีฟอลต์ 6) |
| `--workers N` | จำนวน worker process (ดีฟอลต์ `min(nplanes, cpu_count)`) |

ปกติ **ไม่ต้องเรียกตรง** — GUI สั่งผ่าน `run_with_stats.py` ให้อยู่แล้ว
ถ้า log ขึ้น `No valid planes found` แปลว่ามี DAQ plane หลุดกลางรัน (ดู ITS3 Activity log)

## 3. `run_with_stats.py` — wrapper ของข้อ 1/2 + เก็บสถิติ

เลือก monitor เอง: build + รัน `StdEventMonitor_faster` ถ้าได้, ไม่งั้น fall back ไป
`StdEventMonitor_fast.py`. แล้ว sample CPU/RAM/IO/GPU ของ process tree งานนี้ทุก 0.5 วิ
ปริ้นลง stdout (ไปจบใน `log/`). บรรทัด `Monitor :` ใน Run Stats บอกว่าตัวไหนรันจริง.

```bash
~/sutpct-env/bin/python3 run_with_stats.py <raw_file> -o <output.root>
```

อาร์กิวเมนต์ `<raw_file> -o <root>` ส่งต่อตรงๆ **นี่คือตัวที่ GUI เรียกอัตโนมัติหลังจบทุกรัน**

## 4. `check_gating_consistency.py` — เช็ควินัยการ gate ฝั่ง DAQ

เทียบจำนวน event ที่บันทึกจริง (จาก `log/`) กับ 2 การทำนาย:
- gate ไม่มีผล: `trigger_freq_hz × ระยะเวลารันทั้งหมด`
- gate หยุด trigger เต็มที่: `trigger_freq_hz × ระยะเวลา OPEN รวม`

ถ้าตรงกับอันหลัง = gate ทำงาน (ไม่มี event ตอน gate ปิด)

```bash
~/sutpct-env/bin/python3 check_gating_consistency.py <run.log> <run_gating.csv> [--trigger-freq HZ]
```

| อาร์กิวเมนต์ | ความหมาย |
|---|---|
| `run_log` | `log/run*.log` (ต้องมีบรรทัด `Data events : N`) |
| `gating_csv` | `gating/run*_gating.csv` |
| `--trigger-freq` | override ค่าจาก header ของ gating csv |

⚠️ ตรวจแค่วินัยการ gate ฝั่ง DAQ **ไม่ใช่ตัวจับบีมปลิ้น** — ALPIDE มองไม่เห็นอะไรตอน ungated
อยู่แล้วไม่ว่าจะมีบีมหรือไม่

## 5. `ocr_video.py` — OCR วิดีโอ MU (ใช้ GPU)

อ่านตัวเลข MU1/MU2/rate/progress จาก `mu_video_*.mp4` (ROI 4 แถบซ้อนกัน แถบละ 80px)
ด้วย EasyOCR + validate ช่วงค่า + `_MuPairFilter` (กันค่าสะสมลด/เด้ง)

```bash
# batch: OCR ทุก mp4 ใน ../video/ ที่ยังไม่มี _ocr.csv  (โหลด EasyOCR ครั้งเดียว)
~/sutpct-env/bin/python3 ocr_video.py
~/sutpct-env/bin/python3 ocr_video.py --force            # ทำซ้ำทุกไฟล์

# ไฟล์เดียว
~/sutpct-env/bin/python3 ocr_video.py <mu_video_*.mp4> [--max-frames N]

# diagnostic: dump ภาพ ROI ดิบ (scale เท่าที่ OCR อ่าน) ไว้ดูด้วยตา
~/sutpct-env/bin/python3 ocr_video.py <mu_video_*.mp4> --save-frames 100
```

เอาต์พุตต่อวิดีโอ (ที่เดียวกับไฟล์): `<video>_ocr.csv` (per-frame + timestamp จริง)
และ `<video>_ocr.png` (กราฟ 3 แผง)

GUI **ไม่เรียกตัวนี้อัตโนมัติ** — อัดวิดีโอ + scp ขึ้น `video/` เท่านั้น ต้อง SSH มารันเอง

หมายเหตุ: mu1/mu2 มีเพดานความแม่นจาก moire + font เล็กตอนถ่ายจอ (ยืนยันด้วย `--save-frames`)
mu_rate/progress อ่านชัด — แก้ทาง software ต่อไม่ช่วย ต้องแก้ที่ hardware
