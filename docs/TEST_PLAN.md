# Test Plan — pre-session checkout

รันทุกข้อก่อนเชื่อ `dev` แล้ว merge → `main` / ก่อน beam session จริง
ทำตามลำดับ: A (ไม่ต้องมีฮาร์ดแวร์) → B (ฮาร์ดแวร์ครบ) → C (verify การแก้ล่าสุด)

`[ ]` = ยังไม่ทำ  ·  `[x]` = ผ่าน  ·  `[!]` = fail (จดอาการไว้)

---

## A. Sim mode — ไม่ต้องต่ออุปกรณ์

เปิด: `python3 main.py --sim`  (มี Control Room window เด้งมาด้วย)

### A0. เปิดแอป
- [ ] แอปเปิด ไม่มี traceback ใน terminal
- [ ] Header: ALPIDE / Zaber / FPGA ขึ้นสถานะ (เขียวใน sim)
- [ ] Control Room window เปิดแยก

### A1. Static test — phantom jog
- [ ] แผงซ้าย: กด jog X+ / X− / Y± / R± → ตัวเลขตำแหน่งขยับ ไม่ค้าง
- [ ] กด Home → กลับ 0/0/0

### A2. QA mode — run flow
- [ ] กดปุ่ม **QA** (pill บนขวา) → velocity fields เปิดใช้ได้, Launch default เปิด (ไม่ต้องติ๊ก Enable)
- [ ] กรอก qa_pos X/Y/R + vel X/Y/R (ใต้ speed limit)
- [ ] **Launch default** → EmbeddedTerminal เริ่ม poll, ITS3 session ขึ้น
- [ ] ปุ่มใน progress section เป็น **Start Acquisition**
- [ ] **Start Acquisition** → progress bar เดิน, stage เลื่อนตาม velocity
- [ ] **Stop** → หยุด, dialog **"QA Acquisition Complete"** เด้ง (modal)
- [ ] ปิด dialog → footer กลับ idle, Launch default เปิดอีกครั้ง

### A3. QA mode — speed limit guard
- [ ] ใส่ vel_x = 5 (เกิน 2.5) → กด Start → **"Speed limit exceeded"** เด้ง, ไม่ยอมรัน
- [ ] แก้กลับ ≤ 2.5 → รันได้

### A4. Treatment mode — Control Room sequence
- [ ] กดปุ่ม **Treatment** → velocity fields ปิด (ใช้ max speed)
- [ ] ติ๊ก **Enable** → Launch default เปิด
- [ ] Control Room: **PREPARE** → สถานะเปลี่ยน "Previewing → press PREPARE"
- [ ] **Launch default** ในแอปหลัก → EUDAQ เริ่ม
- [ ] Control Room: **READY** → lamp READY ติด
- [ ] Control Room: **BEAM ON** → lamp BEAM ON ติด, worker เริ่ม acquisition
- [ ] รอครบ Loops → progress section ปิดเอง
- [ ] dialog **"Treatment Acquisition Complete"** เด้ง (non-modal — ต้องไม่ค้างทับกันถ้ารันซ้ำ)
- [ ] Kill beam button เริ่มกะพริบ

### A5. Auto-kill
- [ ] ติ๊ก **Auto kill beam** ก่อนรัน → หลัง run จบ ปุ่มนับถอยหลัง "Kill beam (Ns)"
- [ ] ปล่อยครบ → beam kill อัตโนมัติ, footer กลับ idle
- [ ] รันใหม่ + กด Kill beam เองก่อนครบ → countdown หยุดทันที

### A6. Step scan (X/Y/R step per loop)
- [ ] Treatment, ตั้ง Loops = 3, **R step (degree)** = 3, X/Y step = 0
- [ ] รัน → หลังแต่ละ loop stage หมุน R +3° (ดู phantom label + ITS3 snapshot ถูก force ทุก loop)
- [ ] progress bar format "1/3 → 2/3 → 3/3"

### A7. Plan mode
- [ ] **Load Plan** → เลือก `plan/plan_format_example.csv` → ตารางขึ้น 11 แถว, ทุกแถว status = pending
- [ ] คลิกแถว mode=treatment → tooltip โชว์ Steps/Ctrl, ฟอร์มถูก populate
- [ ] คลิกแถว mode=qa → โหมดสลับเป็น QA อัตโนมัติ, qa_pos/vel ถูก populate
- [ ] **Create Plan** dialog → Import current → Add row → Save CSV → ไฟล์ใช้งานได้ (`csv.DictReader` header ครบ)

### A8. Emergency abort
- [ ] ระหว่างรัน กด **Stop / force stop** → หยุดทันที ไม่ crash, stage หยุด

### A9. ปิดแอป
- [ ] ปิด → ไม่มี traceback, tmux session `ITS3` ถูกลบ (`tmux ls` ไม่เหลือ)

---

## B. ฮาร์ดแวร์จริง — ต่อ ALPIDE + Zaber + FPGA

เปิด: `python3 main.py`

### B0. Connections
- [ ] ALPIDE / Zaber / FPGA → เขียวทั้งหมด (กดปุ่มเพื่อ re-check ได้)
- [ ] Firmware label: ถ้า DAQ ยังไม่ program → **Firmware Toast** เด้ง, flash เสร็จขึ้น "Firmware Installed"
- [ ] (ถ้า flash ค้าง > 180s → toast timeout + ข้อความให้ power-cycle hub — อย่าให้ app ค้าง)

### B1. rsync connect
- [ ] กรอก SSH address + remote path + password → **Connect** → สถานะเขียว "rsync connected"
- [ ] ssh ไปเช็ค: `ls <remote_path>/scripts/` → มี **5 ไฟล์**: `StdEventMonitor_fast.py`, `run_with_stats.py`, `check_gating_consistency.py`, `ocr_video.py`, `README.md`

### B2. QA run — end to end
- [ ] QA mode, ตั้ง qa_pos + vel, Launch → Start Acquisition → รอจบ → Stop
- [ ] **raw ไฟล์โผล่ที่ `<outpath>/raw/`** (ไม่ใช่แบนๆ นอก raw/)
- [ ] rsync toast เด้ง มี % + speed → จบขึ้น "Sent to ..."
- [ ] `<outpath>/log/<run>.log` ถูกสร้าง (local copy)
- [ ] ssh: `<remote_path>/raw/<run>.raw` มา, `<remote_path>/root/<run>.root` ถูกสร้าง (conversion)
- [ ] ssh: `<remote_path>/log/<run>.log` ท้ายไฟล์มี `[STATS]` + `Data events : N` + `ROOT file written`

### B3. Treatment run + step scan จริง
- [ ] Treatment, Enable, Loops ≥ 3, R step = 3 → Launch → CR PREPARE/READY/BEAM ON → รอจบ
- [ ] stage หมุนจริงระหว่าง loop
- [ ] beam-gate: `<remote_path>/gating/<run>_gating.csv` ถูกสร้าง (มี `gate_state,x_mm,y_mm,r_mm`)
- [ ] Kill beam ทำงาน (หรือ auto-kill)

### B4. Trigger freq guard
- [ ] ตั้ง Trigger Freq = 9750 → รัน → ITS3 log ไม่มี `Out of sync`
- [ ] (ถ้าอยากยืนยัน limit) ตั้ง 10000 → รัน → ITS3 log มี `Warning! Out of sync! AL0:.. AL2:..` โผล่ในแถว `dc`

### B5. Camera (ถ้าต่อ)
- [ ] กล้องต่อ + ROI ตั้งไว้ → run → `<outpath>/video/mu_video_*.mp4` มีขนาด > 1 MB (มีเฟรมจริง)
- [ ] ssh: อัปขึ้น `<remote_path>/video/`
- [ ] บน server: `cd <remote_path>/scripts && ~/sutpct-env/bin/python3 ocr_video.py` → สร้าง `_ocr.csv` + `_ocr.png`

---

## C. Verify การแก้ล่าสุด (dev เทียบ main)

### C1. Output layout mirror
- [ ] หลัง B2/B3: `<outpath>/` มีเฉพาะ `raw/` `log/` `video/` (ไม่มีไฟล์แบนๆ, ไม่มี `logs.txt`, ไม่มี `csv/`)
- [ ] ชื่อ subfolder ตรงกับ server (`raw` `log` `video`)

### C2. ITS3 session log format (การแก้หลัก)
- [ ] `<run>.log` ส่วน `--- ITS3 Session Log ---` header = **`ITS3 Log — N snapshots (M with producer detail)`** โดย **M = N** (ไม่ใช่ 0)
- [ ] แต่ละ snapshot มีตาราง `Plane / State / Data EV# / Stat EV# / Message` + แถว `dc`
- [ ] ถ้า M = 0 → euRun format เปลี่ยน → เก็บ raw จาก `/tmp/its3_run_*.log` (ตอนรันอยู่) ส่งมาแก้ regex

### C3. remote_scripts auto-ship
- [ ] ทำ B1 แล้ว 5 ไฟล์ครบ (ครอบคลุมแล้ว)
- [ ] ลองวางไฟล์ dummy `remote_scripts/zzz.py` → connect → มันขึ้น server ด้วย → **ลบ dummy ออก** (เตือน: อย่าทิ้ง scratch ไว้ใน remote_scripts/)

### C4. Empty-video stub (known, ยังไม่แก้)
- [ ] ไม่ต่อกล้อง + มี ROI files → run → `video/mu_video_*.mp4` = ~258 bytes (ไฟล์เปล่า) → SCP ขึ้น server ด้วย
- [ ] รับทราบว่าเป็นพฤติกรรมที่รู้อยู่ (ดู CLAUDE.md / จะแก้ทีหลัง)

### C5. config.json
- [ ] เปิด `config.json` → ไม่มี key `rsync_dest` แล้ว
- [ ] แก้ field ในแอป → ปิดแอป → เปิดใหม่ → ค่าถูกจำ

### C6. Branch
- [ ] `git log --oneline main..dev` — review 20 commits
- [ ] เครื่อง beam อยู่ `dev` (`git branch --show-current`) **หรือ** merge `dev`→`main` แล้ว push

---

## Regression watch (ดูทุก session)

| จุด | อาการถ้าพัง |
|---|---|
| `enable_beam()` DB-9 block | beam ควบคุมผิด — **ห้ามแก้บล็อกนี้** |
| FPGA poll main thread | UI แลค ~1s ทุก 2 วิ (deferred issue) |
| ALPIDE re-enumerate หลัง flash | DAQ หายจาก USB → power-cycle hub |
| Trigger freq ≥ 10000 Hz | out-of-sync ทุกครั้ง (hard limit) |
