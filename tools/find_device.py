# find_device.py
import serial
import serial.tools.list_ports as listports
import usb

RAW_VID=0x04B4
RAW_PID=0x00F3

OLD_VID=0x04B4
OLD_PID=0x00F1

FW_VID=0x1556
FW_PID=0x01B8

def get_port():
    ports = listports.comports()
    # print(ports)
    # for p in ports:
    #     print(p.device)
    for port, desc, hwid in sorted(ports):
        print("{}: {} [{}]".format(port, desc, hwid))
        
def get_uid(dev):
    if dev.idVendor==RAW_VID and dev.idProduct==RAW_PID:
        sn=dev.ctrl_transfer(0xC0,0xA0,0x5010,0xE005,8)
        sn='DAQ-'+''.join(reversed(['%02X'%b for b in sn]))
        return sn
    elif dev.idVendor==FW_VID and dev.idProduct==FW_PID:
        return dev.serial_number
    else:
        assert False,'ERROR: unknown VID/PID'
        
def find_usb():
    DAQs = {
        "DAQ-000904250102082C": 0,
        "DAQ-000904250102061F": 1,
        "DAQ-0009042501141327": 2,
        "DAQ-0009042501141214": 3,
        "DAQ-0009042501020714": 4,
        "DAQ-0009042501141325": 5,
    }
    
    devs=list(usb.core.find(idVendor=RAW_VID,idProduct=RAW_PID,find_all=True))
    unprogrammed_serials=set(get_uid(dev) for dev in devs)
    devs=list(usb.core.find(idVendor=FW_VID,idProduct=FW_PID,find_all=True))
    programmed_serials=set(get_uid(dev) for dev in devs)
    print(sorted([DAQs[serial] for serial in programmed_serials]))

# get_port()
find_usb()