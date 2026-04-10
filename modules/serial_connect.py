import serial
import serial.tools.list_ports as listports
# import ..zaber.connect as zaber_connect
# from zaber import connect as zaber_connect

def get_port(device):
    # device_SNR = {"zaber": "AL0393XP", "fpga": "210183B5A8D0"}
    device_SNR = {"zaber": "AB0NSAIM", "fpga": "210183B5A8D0"}
    fpga_ports = []
    ports = listports.comports()
    for port, desc, hwid in sorted(ports):
        if device_SNR[device] in hwid:
            if device == "fpga":
                fpga_ports.append(port)
            else:
                return port
    if device == "fpga" and len(fpga_ports):
        return fpga_ports[-1]
    raise ConnectionError
        
# print(get_port())      
def get_serial_connect():
    serial_number = "/dev/ttyUSB1"
    baud_rate = 9600
    # serial_port = get_port(serial_number)
    ser = serial.Serial(serial_number, baud_rate)
    return ser

def show_port():
    ports = listports.comports()
    for port, desc, hwid in sorted(ports):
        print("port: {}, desc: {}, hwid: {}".format(port, desc, hwid))
        

# show_port()
# port = "/dev/ttyUSB0"
# conn = zaber_connect.connect(port)
# for x in conn.__dir__():
#     print(x)
# print(conn.get_device(1))
# device_x = conn.get_device(1)
# device_x.identify()
# print(device_x.name)

# device_y = conn.get_device(2)
# device_y.identify()
# print(device_y.name)

# device_rot = conn.get_device(3)
# device_rot.identify()
# print(device_rot.name)

# conn.close()