import zaber_motion.units as zaber_units
import asyncio
from zaber_motion.ascii import Connection

X_MAX = 150.0 #mm
Y_MAX = 40.0 #mm
R_MAX = 360 #mm

def get_current_locations(conn):
    device_x = conn.get_device(1)
    device_x.identify()
    # print(device_x.name)

    device_y = conn.get_device(2)
    device_y.identify()
    # print(device_y.name)

    device_rot = conn.get_device(3)
    device_rot.identify()
    
    return (device_x.get_axis(1).get_position(unit=zaber_units.Units.LENGTH_MILLIMETRES), 
            device_y.get_axis(1).get_position(unit=zaber_units.Units.LENGTH_MILLIMETRES), 
            device_rot.get_axis(1).get_position(unit=zaber_units.Units.ANGLE_DEGREES))

def to_home(conn: Connection):
    device_x = conn.get_device(1)
    device_x.identify()
    # print(device_x.name)

    device_y = conn.get_device(2)
    device_y.identify()
    # print(device_y.name)

    device_rot = conn.get_device(3)
    device_rot.identify()
    
    async def _run():
        await asyncio.gather(
            device_x.get_axis(1).home_async(),
            device_y.get_axis(1).home_async(),
            device_rot.get_axis(1).home_async(),
        )
    asyncio.run(_run())
    
def apply_move(conn, loc):
    device_x = conn.get_device(1)
    device_x.identify()
    # print(device_x.name)

    device_y = conn.get_device(2)
    device_y.identify()
    # print(device_y.name)

    device_rot = conn.get_device(3)
    device_rot.identify()
    
    async def _run():
        await asyncio.gather(
            device_x.get_axis(1).move_absolute_async(loc[0], unit=zaber_units.Units.LENGTH_MILLIMETRES),
            device_y.get_axis(1).move_absolute_async(loc[1], unit=zaber_units.Units.LENGTH_MILLIMETRES),
            device_rot.get_axis(1).move_absolute_async(loc[2], unit=zaber_units.Units.ANGLE_DEGREES),
        )
    asyncio.run(_run())
    return (device_x.get_axis(1).get_position(unit=zaber_units.Units.LENGTH_MILLIMETRES),
            device_y.get_axis(1).get_position(unit=zaber_units.Units.LENGTH_MILLIMETRES),
            device_rot.get_axis(1).get_position(unit=zaber_units.Units.ANGLE_DEGREES))
    
def apply_step(conn: Connection, axis, step):
    device_x = conn.get_device(1)
    device_x.identify()
    # print(device_x.name)

    device_y = conn.get_device(2)
    device_y.identify()
    # print(device_y.name)

    device_rot = conn.get_device(3)
    device_rot.identify()
    
    if axis == 0:
        device_x.get_axis(1).move_relative(step, unit=zaber_units.Units.LENGTH_MILLIMETRES)
    elif axis == 1:
        device_y.get_axis(1).move_relative(step, unit=zaber_units.Units.LENGTH_MILLIMETRES)
    else:
        device_rot.get_axis(1).move_relative(step, unit=zaber_units.Units.ANGLE_DEGREES)
    
    return (device_x.get_axis(1).get_position(unit=zaber_units.Units.LENGTH_MILLIMETRES), 
            device_y.get_axis(1).get_position(unit=zaber_units.Units.LENGTH_MILLIMETRES), 
            device_rot.get_axis(1).get_position(unit=zaber_units.Units.ANGLE_DEGREES))

def apply_steps(conn: Connection, steps):
    device_x = conn.get_device(1)
    device_x.identify()
    # print(device_x.name)

    device_y = conn.get_device(2)
    device_y.identify()
    # print(device_y.name)

    device_rot = conn.get_device(3)
    device_rot.identify()
    
    async def _run():
        await asyncio.gather(
            device_x.get_axis(1).move_relative_async(steps[0], unit=zaber_units.Units.LENGTH_MILLIMETRES),
            device_y.get_axis(1).move_relative_async(steps[1], unit=zaber_units.Units.LENGTH_MILLIMETRES),
            device_rot.get_axis(1).move_relative_async(steps[2], unit=zaber_units.Units.ANGLE_DEGREES),
        )
    asyncio.run(_run())
    return (device_x.get_axis(1).get_position(unit=zaber_units.Units.LENGTH_MILLIMETRES),
            device_y.get_axis(1).get_position(unit=zaber_units.Units.LENGTH_MILLIMETRES),
            device_rot.get_axis(1).get_position(unit=zaber_units.Units.ANGLE_DEGREES))
    
def apply_steps_loop(conn: Connection, steps, loop):
    device_x = conn.get_device(1)
    device_x.identify()
    # print(device_x.name)

    device_y = conn.get_device(2)
    device_y.identify()
    # print(device_y.name)

    device_rot = conn.get_device(3)
    device_rot.identify()

    coroutine_x = device_x.get_axis(1).move_relative_async(steps[0], unit=zaber_units.Units.LENGTH_MILLIMETRES)
    coroutine_y = device_y.get_axis(1).move_relative_async(steps[1], unit=zaber_units.Units.LENGTH_MILLIMETRES)
    coroutine_r = device_rot.get_axis(1).move_relative_async(steps[2], unit=zaber_units.Units.ANGLE_DEGREES)

    asyncio.set_event_loop(loop)
    move_coroutine = asyncio.gather(coroutine_x,coroutine_y,coroutine_r)

    loop.run_until_complete(move_coroutine)
    return (device_x.get_axis(1).get_position(unit=zaber_units.Units.LENGTH_MILLIMETRES),
            device_y.get_axis(1).get_position(unit=zaber_units.Units.LENGTH_MILLIMETRES),
            device_rot.get_axis(1).get_position(unit=zaber_units.Units.ANGLE_DEGREES))


def stop_all(conn: Connection):
    device_x = conn.get_device(1)
    device_y = conn.get_device(2)
    device_rot = conn.get_device(3)
    async def _run():
        await asyncio.gather(
            device_x.get_axis(1).stop_async(),
            device_y.get_axis(1).stop_async(),
            device_rot.get_axis(1).stop_async(),
        )
    asyncio.run(_run())
