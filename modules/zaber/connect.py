from zaber_motion.ascii import Connection

def connect(port):
    connection = Connection.open_serial_port(port)
    # device_x = connection.get_device(1)
    # device_x.identify()
    # # print(device_x.name)

    # device_y = connection.get_device(2)
    # device_y.identify()
    # # print(device_y.name)

    # device_rot = connection.get_device(3)
    # device_rot.identify()
    # # print(device_rot.name)
    
    # device_x.get_axis(1).move_absolute_async()
    
    # return device_x, device_y, device_rot
    return connection