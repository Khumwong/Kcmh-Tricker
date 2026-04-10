import time
import datetime
import serial
import serial.tools.list_ports as listports

def get_port(device):
    device_SNR = {"zaber": "AL0393XP", "fpga": "210183B5A8D0"}
    ports = listports.comports()
    for port, desc, hwid in sorted(ports):
        if device_SNR[device] in hwid and "LOCATION=1-3:1.0" in hwid:
            return port
    raise ConnectionError

def show_port():
    ports = listports.comports()
    # print(ports)
    # for p in ports:
    #     print(p.device)
    for port, desc, hwid in sorted(ports):
        print("{}, {}, {}".format(port, desc, hwid))

print(show_port())

# Define serial port settings
# port = '/dev/ttyUSB2'  # Change this to the appropriate COM port
# baudrate = 115200
# parity = serial.PARITY_NONE
# bytesize = serial.EIGHTBITS
# stopbits = serial.STOPBITS_ONE  # Change this to the desired number of stop bits

# def write_data(sers):
#     ser.write(b'\x00')
#     ser.write(b'\x01')
#     ser.write(b'\x03')
#     ser.write(b'\x07')
#     ser.write(b'\x0F')
#     ser.write(b'\x1F')
#     ser.write(b'\x3F')

# def is_success_read(b, ser, time_out=5):
#     i_time = datetime.datetime.now()
#     if ser.is_open:
#         while True:
#             b_read = ser.read()
#             if b_read == b:
#                 return True
#             f_time = datetime.datetime.now()
#             if (f_time - i_time).seconds >= time_out:
#                 return False

# try:
#     # Open serial port
#     ser = serial.Serial(port=get_port("fpga"), baudrate=baudrate, parity=parity,
#                         bytesize=bytesize, stopbits=stopbits, timeout=1)
#     x = 254
#     byte_list = [b'\x00', b'\x01', b'\x00', b'\x00', b'\x00', b'\x00', b'\xFF', b'\x27',
#                  b'\x10', x.to_bytes(1, 'big')]
#     byte_list1 = [b'\x00', b'\x01', b'\x00', b'\x00', b'\x00', b'\x00', b'\xFF', b'\x27',
#                  b'\x10', -127]
#     # print(ser.is_open)
#     # Check if the port is open

#     for b_send in byte_list:
#         ser.write(b_send)
#     # ser.write(255)
#     # print(is_success_read(b'\x02', ser))

#     # if ser.is_open:
#     #     print(f"Serial port {port} opened successfully.")
        
#     #     while True:
#     #         ser_read = ser.read()
#     #         print("{}".format(ser_read))

#         # Read or write data here
        
#         # Close the serial port when done
#     ser.close()
#     # print("Serial port closed.")

# except serial.SerialException as e:
#     print(f"Error: {e}")