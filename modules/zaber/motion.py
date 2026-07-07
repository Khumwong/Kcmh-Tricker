import zaber_motion.units as zaber_units
import asyncio
from zaber_motion.ascii import Connection

X_MAX = 150.0 #mm
Y_MAX = 40.0 #mm
R_MAX = 360 #mm

def poll_positions(conn: Connection):
    """Lightweight position read for real-time polling — no identify() call."""
    return (
        conn.get_device(1).get_axis(1).get_position(unit=zaber_units.Units.LENGTH_MILLIMETRES),
        conn.get_device(2).get_axis(1).get_position(unit=zaber_units.Units.LENGTH_MILLIMETRES),
        conn.get_device(3).get_axis(1).get_position(unit=zaber_units.Units.ANGLE_DEGREES),
    )

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
    
def apply_steps_loop_vel(conn: Connection, steps, velocities, loop):
    """Like apply_steps_loop but uses per-axis velocity; skips axes where velocity=0."""
    device_x   = conn.get_device(1); device_x.identify()
    device_y   = conn.get_device(2); device_y.identify()
    device_rot = conn.get_device(3); device_rot.identify()

    coros = []
    if steps[0] != 0 and velocities[0] > 0:
        coros.append(device_x.get_axis(1).move_relative_async(
            steps[0], unit=zaber_units.Units.LENGTH_MILLIMETRES,
            velocity=velocities[0],
            velocity_unit=zaber_units.Units.VELOCITY_MILLIMETRES_PER_SECOND))
    if steps[1] != 0 and velocities[1] > 0:
        coros.append(device_y.get_axis(1).move_relative_async(
            steps[1], unit=zaber_units.Units.LENGTH_MILLIMETRES,
            velocity=velocities[1],
            velocity_unit=zaber_units.Units.VELOCITY_MILLIMETRES_PER_SECOND))
    if steps[2] != 0 and velocities[2] > 0:
        coros.append(device_rot.get_axis(1).move_relative_async(
            steps[2], unit=zaber_units.Units.ANGLE_DEGREES,
            velocity=velocities[2],
            velocity_unit=zaber_units.Units.ANGULAR_VELOCITY_DEGREES_PER_SECOND))

    asyncio.set_event_loop(loop)
    if coros:
        loop.run_until_complete(asyncio.gather(*coros))

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


def get_max_speeds(conn: Connection):
    """Return (max_vx_mm_s, max_vy_mm_s, max_vr_deg_s) from device settings."""
    dev_x   = conn.get_device(1); dev_x.identify()
    dev_y   = conn.get_device(2); dev_y.identify()
    dev_rot = conn.get_device(3); dev_rot.identify()
    max_x = dev_x.get_axis(1).settings.get("maxspeed",   unit=zaber_units.Units.VELOCITY_MILLIMETRES_PER_SECOND)
    max_y = dev_y.get_axis(1).settings.get("maxspeed",   unit=zaber_units.Units.VELOCITY_MILLIMETRES_PER_SECOND)
    max_r = dev_rot.get_axis(1).settings.get("maxspeed", unit=zaber_units.Units.ANGULAR_VELOCITY_DEGREES_PER_SECOND)
    return (max_x, max_y, max_r)


def move_velocity(conn: Connection, vx: float, vy: float, vr: float):
    device_x   = conn.get_device(1); device_x.identify()
    device_y   = conn.get_device(2); device_y.identify()
    device_rot = conn.get_device(3); device_rot.identify()
    coros = []
    if vx != 0:
        coros.append(device_x.get_axis(1).move_velocity_async(
            vx, unit=zaber_units.Units.VELOCITY_MILLIMETRES_PER_SECOND))
    if vy != 0:
        coros.append(device_y.get_axis(1).move_velocity_async(
            vy, unit=zaber_units.Units.VELOCITY_MILLIMETRES_PER_SECOND))
    if vr != 0:
        coros.append(device_rot.get_axis(1).move_velocity_async(
            vr, unit=zaber_units.Units.ANGULAR_VELOCITY_DEGREES_PER_SECOND))
    if coros:
        async def _run():
            await asyncio.gather(*coros)
        asyncio.run(_run())


def move_to_target(conn: Connection, x, y, r, sx: float = 0, sy: float = 0, sr: float = 0):
    """Non-blocking absolute move to position at speed. None = skip axis, speed 0 = max."""
    device_x   = conn.get_device(1); device_x.identify()
    device_y   = conn.get_device(2); device_y.identify()
    device_rot = conn.get_device(3); device_rot.identify()
    coros = []
    if x is not None:
        kw = dict(unit=zaber_units.Units.LENGTH_MILLIMETRES, wait_until_idle=False)
        if sx:
            kw['velocity'] = sx
            kw['velocity_unit'] = zaber_units.Units.VELOCITY_MILLIMETRES_PER_SECOND
        coros.append(device_x.get_axis(1).move_absolute_async(x, **kw))
    if y is not None:
        kw = dict(unit=zaber_units.Units.LENGTH_MILLIMETRES, wait_until_idle=False)
        if sy:
            kw['velocity'] = sy
            kw['velocity_unit'] = zaber_units.Units.VELOCITY_MILLIMETRES_PER_SECOND
        coros.append(device_y.get_axis(1).move_absolute_async(y, **kw))
    if r is not None:
        kw = dict(unit=zaber_units.Units.ANGLE_DEGREES, wait_until_idle=False)
        if sr:
            kw['velocity'] = sr
            kw['velocity_unit'] = zaber_units.Units.ANGULAR_VELOCITY_DEGREES_PER_SECOND
        coros.append(device_rot.get_axis(1).move_absolute_async(r, **kw))
    if coros:
        async def _run():
            await asyncio.gather(*coros)
        asyncio.run(_run())


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
