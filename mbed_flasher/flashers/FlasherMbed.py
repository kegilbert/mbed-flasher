"""
Copyright 2016 ARM Limited

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import logging
import six
from os.path import join, abspath, isfile
import os
import platform
from time import sleep, time
from threading import Thread
from mbed_flasher.flashers.enhancedserial import EnhancedSerial
from serial.serialutil import SerialException
import hashlib
import mbed_lstools
from subprocess import PIPE, Popen


class FlasherMbed(object):
    name = "mbed"
    FLASHING_VERIFICATION_TIMEOUT = 100

    def __init__(self):
        self.logger = logging.getLogger('mbed-flasher')

    @staticmethod
    def get_supported_targets():
        """Load target mapping information
        """
        mbeds = mbed_lstools.create()
        return sorted(set(mbeds.manufacture_ids.values()))

    @staticmethod
    def get_available_devices():
        mbeds = mbed_lstools.create()
        return mbeds.list_mbeds()
        
    def reset_board(self, serial_port):
        try:
            port = EnhancedSerial(serial_port)
        except SerialException as e:
            self.logger.info("reset could not be sent")
            self.logger.error(e)
            if e.message.find('could not open port') != -1:
                print('Reset could not be given. Close your Serial connection to device.')
            return -6
        port.baudrate = 115200
        port.timeout = 1
        port.xonxoff = False
        port.rtscts = False
        port.flushInput()
        port.flushOutput()

        if port:
            self.logger.info("sendBreak to device to reboot")
            result = port.safe_sendBreak()
            if result:
                self.logger.info("reset completed")
            else:
                self.logger.info("reset failed")
        port.close()
    
    def auxiliary_drive_check(self, drive):
        out = os.listdir(drive[0])
        for item in out:
            if item.find('.HTM') != -1:
                break
        else:
            return False
        if drive[1] not in out:
            return True
       
    def runner(self, drive):
        start_time = time()
        while True:
            sleep(2)
            if platform.system() == 'Windows':
                proc = Popen(["dir", drive[0]], stdin=PIPE, stdout=PIPE, stderr=PIPE, shell=True)
            else:
                proc = Popen(["ls", drive[0]], stdin=PIPE, stdout=PIPE, stderr=PIPE)
            out = proc.stdout.read()
            proc.communicate()
            if out.find(b'.HTM') != -1:
                if out.find(drive[1].encode()) == -1:
                    break
            if platform.system() == 'Windows':
                if not out:
                    if self.auxiliary_drive_check(drive):
                        break
            if time() - start_time > self.FLASHING_VERIFICATION_TIMEOUT:
                self.logger.debug("re-mount check timed out for %s" % drive[0])
                break
                
    def check_points_unchanged(self, target):
        new_target = {}
        if platform.system() == 'Windows':
            mbeds = mbed_lstools.create()
            if target['serial_port'] != mbeds.get_mbed_com_port(target['target_id']):
                new_target['serial_port'] = mbeds.get_mbed_com_port(target['target_id'])
        elif platform.system() == 'Darwin':
            pass
        else:
            for line in os.popen('ls -oA /dev/serial/by-id/').read().splitlines():
                if line.find(target['target_id']) != -1:
                    if target['serial_port'].split('/')[-1] != line.split('/')[-1]:
                        if 'serial_port' not in new_target:
                            new_target['serial_port'] = '/dev/' + line.split('/')[-1]
                        else:
                            self.logger.error("target_id %s has more than 1 "
                                              "serial port in the system" % target['target_id'])
                            return -10
            dev_points = []
            for dev_line in os.popen('ls -oA /dev/disk/by-id/').read().splitlines():
                if dev_line.find(target['target_id']) != -1:
                    if 'dev_point' not in new_target:
                        new_target['dev_point'] = '/dev/' + dev_line.split('/')[-1]
                    else:
                        self.logger.error("target_id %s has more than 1 "
                                          "device point in the system" % target['target_id'])
                        return -11
            if dev_points:
                for i in range(10):
                    for_break = False
                    mounts = os.popen('mount |grep vfat').read().splitlines()
                    for mount in mounts:
                        if mount.find(new_target['dev_point']) != -1:
                            if target['mount_point'] == mount.split('on')[1].split('type')[0].strip():
                                for_break = True
                                break
                            else:
                                new_target['mount_point'] = mount.split('on')[1].split('type')[0].strip()
                                for_break = True
                                break
                        sleep(1)
                    if for_break:
                        break
                else:
                    self.logger.error("vfat mount point for %s did not re-appear in the system in 10 seconds" % 
                                      target['target_id'])
                    return -12
        
        if new_target:
            if 'serial_port' in new_target:
                self.logger.debug("serial port %s has changed to %s" %
                                  (target['serial_port'], new_target['serial_port']))
            else:
                self.logger.debug("serial port %s has not changed" % target['serial_port'])
            if 'mount_point' in new_target:
                self.logger.debug("mount point %s has changed to %s" %
                                  (target['mount_point'], new_target['mount_point']))
            else:
                self.logger.debug("mount point %s has not changed" % target['mount_point'])
            new_target['target_id'] = target['target_id']
            return new_target
        else:
            return target
            
    def flash(self, source, target, method, no_reset):
        """copy file to the destination
        :param source: binary to be flashed
        :param target: target to be flashed
        :param method: method to use when flashing
        :param no_reset: do not reset flashed board at all
        """
        if method == 'pyocd':
            self.logger.debug("pyOCD selected for flashing")
            try:
                from pyOCD.board import MbedBoard
            except ImportError:
                print('pyOCD missing, install\n')
                return -8
        if method == 'edbg':
            self.logger.debug("edbg is not supported for Mbed devices")
            return -13
        
        mount_point = os.path.abspath(target['mount_point'])
        (head, tail) = os.path.split(os.path.abspath(source))
        destination = abspath(join(mount_point, tail))
        
        if isinstance(source, six.string_types):
            if method == 'pyocd':
                try:
                    with MbedBoard.chooseBoard(board_id=target["target_id"]) as board:
                        ocd_target = board.target
                        ocd_flash = board.flash
                        self.logger.debug("resetting device: %s" % target["target_id"])
                        sleep(0.5)  # small sleep for lesser HW ie raspberry
                        ocd_target.reset()
                        self.logger.debug("flashing device: %s" % target["target_id"])
                        ocd_flash.flashBinary(source)
                        self.logger.debug("resetting device: %s" % target["target_id"])
                        sleep(0.5)  # small sleep for lesser HW ie raspberry
                        ocd_target.reset()
                    return 0
                except AttributeError as e:
                    self.logger.error("Flashing failed: %s. tid=%s" % (e, target["target_id"]))
                    return -4
            else:
                try:
                    if 'serial_port' in target and not no_reset:
                        self.reset_board(target['serial_port'])
                        sleep(0.1)
                    if platform.system() == 'Windows':
                        with open(source, 'rb') as f:
                            aux_source = f.read()
                            self.logger.debug("SHA1: %s" % hashlib.sha1(aux_source).hexdigest())
                        self.logger.debug("copying file: %s to %s" % (source, destination))
                        os.system("copy %s %s" % (os.path.abspath(source), destination))
                    else:
                        self.logger.debug('read source file')
                        with open(source, 'rb') as f:
                            aux_source = f.read()
                        if not aux_source:
                            self.logger.error("File couldn't be read")
                            return -7
                        self.logger.debug("SHA1: %s" % hashlib.sha1(aux_source).hexdigest())
                        self.logger.debug("writing binary: %s (size=%i bytes)", destination, len(aux_source))

                        def get_me_file():
                            if platform.system() == 'Darwin':
                                return os.open(destination, os.O_CREAT | os.O_TRUNC | os.O_RDWR | os.O_SYNC)
                            else:
                                return os.open(destination, os.O_CREAT | os.O_DIRECT | os.O_TRUNC | os.O_RDWR)
                        new_file = get_me_file()
                        os.write(new_file, aux_source)
                        os.close(new_file)
                    self.logger.debug("copy finished")
                    sleep(4)
                    
                    new_target = self.check_points_unchanged(target)
                    
                    if isinstance(new_target, int):
                        return new_target
                    else:
                        t = Thread(target=self.runner, args=([target['mount_point'], tail],))
                        t.start()
                        while t.is_alive():
                            t.join(2.5)
                        if not no_reset:
                            if 'serial_port' in new_target:
                                self.reset_board(new_target['serial_port'])
                            else:
                                self.reset_board(target['serial_port'])
                            sleep(0.4)
                            
                        # verify flashing went as planned
                        self.logger.debug("verifying flash")
                        if 'mount_point' in new_target:
                            mount = new_target['mount_point']
                        else:
                            mount = target['mount_point']
                        if isfile(join(mount, 'FAIL.TXT')):
                            with open(join(mount, 'FAIL.TXT'), 'r') as fault:
                                fault = fault.read().strip()
                            self.logger.error("Flashing failed: %s. tid=%s" % (fault, target["target_id"]))
                            return -4
                        if isfile(join(mount, 'ASSERT.TXT')):
                            with open(join(mount, 'ASSERT.TXT'), 'r') as fault:
                                fault = fault.read().strip()
                            self.logger.error("Flashing failed: %s. tid=%s" % (fault, target))
                            return -4
                        if isfile(join(mount, tail)):
                            self.logger.error("Flashing failed: File still present in mount point. tid info: %s" %
                                              target)
                            return -15
                        self.logger.debug("ready")
                        return 0
                except IOError as err:
                    self.logger.error(err)
                    raise err
                except OSError as e:
                    self.logger.error("Write failed due to OSError")
                    self.logger.error(e)
                    return -14
