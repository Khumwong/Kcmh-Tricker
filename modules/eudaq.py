# modules/eudaq.py
import subprocess
import os
from os import path
import time
import glob


EUDAQ_DC      = "dc"
EUDAQ_ID      = "3"
CHIPID        = "16"
VCLIP         = "0"
IDB           = "29"
STROBE_LENGTH = "100"
ITHR          = "60"

VCASNS = ["54", "55", "56", "56", "57", "55"]
VCASN2S = ["66", "67", "68", "68", "69", "67"]

SERIALS = [
    "DAQ-000904250102082C",
    "DAQ-000904250102061F",
    "DAQ-0009042501141327",
    "DAQ-0009042501141214",
    "DAQ-0009042501020714",
    "DAQ-0009042501141325"
        ]
EUDAQ_DIR = "/home/santa/eudaq2/user/ITS3/misc/"

def gen_its3_ini(num_alpides):
    alpide_names = [f"ALPIDE_plane_{i}" for i in range(num_alpides)]
    with open(path.join(EUDAQ_DIR, 'ITS3_auto_gen.ini'), 'w') as f:
        f.write("[RunControl]\n")
        f.write(f"dataproducers  = {','.join(alpide_names)}\n")
        f.write("loggers     = \n")
        f.write("collectors  = dc\n")
        f.write("configs     = ITS3-align-planes-Vbb0-gen.conf\n")
        f.write("\n")
        f.write("[DataCollector.dc]\n")
        f.write(f"dataproducers  = {','.join(alpide_names)}\n")
        f.write("\n")

        for i in range(num_alpides):
            f.write(f"[Producer.ALPIDE_plane_{i}]\n")
            f.write(f"serial      = {SERIALS[i]}\n")
            f.write(f"plane       = {i}\n")
            f.write(f"triggermode = {'primary' if i == 0 else 'replica'}\n")
            f.write("\n") 

def gen_its3_conf(num_alpides, num_evt, strobe_length, i_threshold, outpath):
    alpide_names = [f"ALPIDE_plane_{i}" for i in range(num_alpides)]
    with open(path.join(EUDAQ_DIR, 'ITS3-align-planes-Vbb0-gen.conf'), 'w') as f:
        f.write("[RunControl]\n")
        f.write("EUDAQ_CTRL_PRODUCER_LAST_START = ALPIDE_plane_0\n")
        f.write("EUDAQ_CTRL_PRODUCER_FIRST_STOP = ALPIDE_plane_0\n")
        f.write(f"NEVENTS    = {num_evt}\n")
        f.write("\n")

        for i in range(num_alpides):
            f.write(f"[Producer.ALPIDE_plane_{i}]\n")
            if i == 0:
                f.write(f"fixedbusy     = 80000\n")
                f.write(f"minspacing    =  8000\n")
            f.write("EUDAQ_DC      = dc\n")
            f.write(f"EUDAQ_ID      = {i}\n")
            f.write("CHIPID        = 16\n")
            f.write("VCLIP         = 0\n")
            f.write("IDB           = 29\n")
            f.write(f"STROBE_LENGTH = {strobe_length}\n")
            f.write(f"ITHR          = {i_threshold}\n")
            f.write(f"VCASN         = {VCASNS[i]}\n")
            f.write(f"VCASN2        = {VCASN2S[i]}\n")
            f.write("\n")

        f.write(f"[DataCollector.dc]\n")
        f.write(f"EUDAQ_FW = native\n")
        # output path
        #out_path = '/home/directory'
        f.write(f"EUDAQ_FW_PATTERN = {path.join(outpath, 'run$6R_$12D$X')}\n")

def run(fname):
    # fname = '_'.join("X0Y0Z0R0, stp5rpt4, e70MeV, 1000MU, 200nA".split(', '))
    start_sh = "ITS3start_auto.sh"
    its3_ini = "ITS3_auto.ini"
    conf = "ITS3-align-6plane-Vbb0-auto.conf"
    conf_gen = "ITS3-align-6plane-Vbb0-auto-gen.conf"
    eudaq_dir = "/home/santa/eudaq2/user/ITS3/misc/"
    conf_path = path.join(eudaq_dir, conf)
    conf_gen_path = path.join(eudaq_dir, conf_gen)
    with open(conf_path, 'r') as f:
        read_lines = f.readlines()
    new_lines = []
    for line in read_lines:
        line = line.replace('{name}', fname)
        line = line.replace('{outpath}', path.join(os.getcwd(), 'output'))
        new_lines.append(line)
    with open(conf_gen_path, 'w') as f:
        f.writelines(new_lines)
    command = f"cd {eudaq_dir} && ./{start_sh} && tmux a -t ITS3"
    process = subprocess.Popen(['gnome-terminal', '--', 'bash', '-c', command])
    return process.pid

def stop(pid):
    time.sleep(1)
    subprocess.run(['tmux', 'send-keys', '-t', 'ITS3', 'T'])
    time.sleep(5)
    subprocess.run(['tmux', 'kill-session', '-t', 'ITS3'])
    try:
        subprocess.run(['kill', '-9', f"-{pid}"])
    except:
        pass

    
def stop_auto(content, outfile):
    os.chdir('./output')
    file_list = filter(os.path.isfile, os.listdir('.'))
    sorted_files = sorted(file_list, key=os.path.getmtime)
    outfile.write(" => ".join(sorted_files[-1], content))
    outfile.write("\n")
    time.sleep(1)
    subprocess.run(['tmux', 'send-keys', '-t', 'ITS3', 'T'])
    time.sleep(5)
    subprocess.run(['tmux', 'kill-session', '-t', 'ITS3'])
    outfile.close()

def default_run(qt_args, outpath):
    start_sh = "ITS3start_auto.sh"
    start_sh_gen = "ITS3start_auto_gen.sh"
    with open(path.join(EUDAQ_DIR, start_sh), 'r') as f:
        lines = f.readlines()
    with open(path.join(EUDAQ_DIR, start_sh_gen), 'w') as f:
        for line in lines:
            if "{num_alpides}" in line:
                f.write(line.replace("{num_alpides}", qt_args["num_alpides"].text()))
            else:
                f.write(f"{line}")
    eudaq_dir = "/home/santa/eudaq2/user/ITS3/misc/"
    gen_its3_ini(int(qt_args["num_alpides"].text()))
    gen_its3_conf(int(qt_args["num_alpides"].text()), int(qt_args["num_events"].text()), int(qt_args["strobe"].text()),
                   int(qt_args["ithr"].text()), outpath)
    # รัน startup script แบบ headless (script จะสร้าง tmux session ITS3 เอง)
    command = f"cd {eudaq_dir} && bash ./{start_sh_gen}"
    process = subprocess.Popen(['bash', '-c', command])
    return process.pid
    
def install_firware():
    alpide_dir = "/home/santa/alpide-daq-software"
    command_alpide = f"alpide-daq-program --fx3=./tmp/fx3.img --fpga=./tmp/fpga-v1.0.0.bit --all"
    command = f'gnome-terminal -- bash -c "cd {alpide_dir} && {command_alpide}; exec bash"'
    process = subprocess.Popen(command, shell=True)

def install_firmware_auto(parent_widget=None):
    """รัน firmware installer พร้อม progress popup — block UI จนเสร็จ"""
    from modules.ui.firmware_toast import FirmwareToast
    toast = FirmwareToast(parent=parent_widget)
    toast.show_centered(parent_widget)

    alpide_dir = "/home/santa/alpide-daq-software"
    result = subprocess.run(
        ["alpide-daq-program", "--fx3=./tmp/fx3.img", "--fpga=./tmp/fpga-v1.0.0.bit", "--all"],
        cwd=alpide_dir
    )
    success = result.returncode == 0
    toast.set_done(success)
    return success

def monitor(filepath):
    std_exc = "/home/santa/eudaq2/bin/StdEventMonitor"
    command = f'gnome-terminal -- bash -c "{std_exc} -d {filepath}; exec bash"'
    process = subprocess.Popen(command, shell=True)
