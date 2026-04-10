import serial
import time

def check_connection(port):
    baudrate = 115200
    parity = serial.PARITY_NONE
    bytesize = serial.EIGHTBITS
    stopbits = serial.STOPBITS_ONE
    
    try:
        ser = serial.Serial(port=port, baudrate=baudrate, parity=parity,
                            bytesize=bytesize, stopbits=stopbits, timeout=1)
        ser.close()
        return True
    except:
        return False
    
    