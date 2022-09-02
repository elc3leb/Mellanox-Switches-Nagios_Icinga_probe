#!/usr/bin/env python
# -*- coding: utf-8 -*
#
# ----------------------------------------------------------------------------
#  This Plugin is used to gather the memory usage of an ib-switch by using the
#  REST-API
#
# 
#  Update : 2022/04/26 - Adaptation for using the JSON API
# As of the September release of software version 3.8.2000, the XML user accounts
# will no longer be supported and the XML gateway will be closed. Access through
# XML will no longer be available.
# Interfaces will only be available through SNMP and JSON 
# ----------------------------------------------------------------------------

import re
import os
import signal
import sys
import time
import json
import xml.dom.minidom
from optparse import OptionParser

import requests
import urllib3

# disable insecure warning
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# define return codes
#
EXIT = {'OK': 0, 'WARNING': 1, 'CRITICAL': 2, 'UNKNOWN': 3}


# sub for verbose output
def VerboseOutput(Message):
    print("[%s] - %s" % (time.strftime("%Y%m%d %H:%M:%S"), Message))


# sub for print a message ans exit
def PrintAndExit(Message, PerfData, State):
    if Options.CheckMK:
        if not PerfData:
            PerfDataStr = '-'
        else:
            PerfDataStr = '|'.join(PerfData)
        print("%s %s %s %s - %s" % (EXIT[State], os.path.basename(sys.argv[0]), PerfDataStr, State[:4], Message))
    else:
        if PerfData:
            Message = Message + "|" + ' '.join(PerfData)
        print("%s" % (Message))

    sys.exit(EXIT[State])


# Signal handler
def SignalHandler(SigNum, Frame):
    Message = ''

    # SIGALRM
    if SigNum == 14:
        Message = 'plugin timed out after %s sec!' % str(Options.timeout)

    # SIGTERM
    if SigNum == 15:
        Message = 'plugin killed by monitoring'

    PrintAndExit(Message, None, 'UNKNOWN')


# fill option vars
#
usage = '''Usage: %prog [option]'''

parser = OptionParser(usage=usage)
parser.add_option('-H', '--host', type='string', dest='host')
parser.add_option('-u', '--user', type='string', dest='user', default='admin')
parser.add_option('-p', '--password', type='string', dest='password', default='************')
parser.add_option('--memory-critical', type='int', dest='mcritical', default='90')
parser.add_option('--memory-warning', type='int', dest='mwarning', default='85')
parser.add_option('--load-critical', type='string', dest='lcritical', default='4.5,4,3.5')
parser.add_option('--load-warning', type='string', dest='lwarning', default='4,3.5,3.40')
parser.add_option('--temp-critical', type='string', dest='tcritical', default='70,60,90',
                  help='Ex: \'90,100,70\' where 90=CPU, 100=Asic, 70=QSFP')
parser.add_option('--temp-warning', type='string', dest='twarning', default='60,55,82',
                  help='Ex: \'80,90,60\'  where 90=CPU, 100=Asic, 70=QSFP')
parser.add_option('-t', '--timeout', type='int', dest='timeout', default=60)
parser.add_option('-v', '--verbose', dest='verbose', action='store_true')
parser.add_option('-m', '--checkmk', dest='CheckMK', default=0, action='store_true')

(Options, args) = parser.parse_args()

# set handler for SIGTERM and SIGKILL
#
signal.signal(signal.SIGTERM, SignalHandler)
signal.signal(signal.SIGALRM, SignalHandler)

# ----------------------------------------------------------------------------
#
# Sanity checks
#
# ----------------------------------------------------------------------------

if Options.host is None:
    PrintAndExit('Hostname missing!', None, 'UNKNOWN')

if Options.timeout > 0:
    signal.alarm(Options.timeout)

# ----------------------------------------------------------------------------
#
# MAIN
#
# ----------------------------------------------------------------------------

def execute_single_command(ip, user, password, cmd):
    urllib3.disable_warnings()
    url = 'https://{0}/admin/launch?script=rh&template=json-request&action=json-login'.format(ip)
    body = {
        "username": user,
        "password": password,
        "cmd": cmd
        }

    if isinstance(cmd, list):
        body = {
            "username": user,
            "password": password,
            "commands": cmd
        }

    try:
        response = requests.post(url, json=body, verify=False, timeout=Options.timeout)
    except requests.exceptions.RequestException as e:
        raise SystemExit(e)

    if response:
        return json.loads(response.text)
    else:
        return {}

data_mem_load = execute_single_command(Options.host,Options.user,Options.password,'show version')
data_temp = execute_single_command(Options.host,Options.user,Options.password,'show temperature')
data_module = execute_single_command(Options.host,Options.user,Options.password,'show module')

asic_temps = []
sib_temps = []
MissingModules = []
FailedModules = []

# Modules parsing 
if len(data_module['data']) :
    for k,v in data_module['data'].items() :
        #print(k)
        if 'not-present' in v[-1]['Status'] :
            MissingModules.append(k)
        if 'failed' in v[-1]['Status'] :
            FailedModules.append(k)

# Load & Memory Parsing 
for k,v in data_mem_load['data'].items() : 
    if 'CPU load' in k :
        Load1, Load5, Load15 = v.split('/')
    if 'System memory' in k :
        Used, Free, Total = v.split('/')

Used = int(Used.replace('MB used','').replace(' ',''))
Free = int(Free.replace('MB free','').replace(' ',''))
Total = int(Total.replace('MB total','').replace(' ',''))
Load1 = Load1.replace(' ','')
Load5 = Load5.replace(' ','')
Load15 = Load15.replace(' ','')

for line in data_temp['data']['Temperature per module'] : 
    # CS7500 parsing 
    if 'MGMT1' in line : 
        for line in data_temp['data']['Temperature per module']['MGMT1'] :
            if 'CPU package Sensor' in line['Component'] :
                cpu_temp = line['CurTemp (Celsius)']
        json_sib = data_temp['data']['Temperature per module']
        for line in json_sib :
            modules = json_sib[line]
            for module in modules :
                if 'SIB' in module['Component'] :
                    sib_temps.append(module['CurTemp (Celsius)'])
                if 'ASIC' in module['Component'] :
                    asic_temps.append(module['CurTemp (Celsius)'])
    # CS7500 parsing 
    elif 'MGMT2' in line : 
        for line in data_temp['data']['Temperature per module']['MGMT2'] :
            if 'CPU package Sensor' in line['Component'] :
                cpu_temp = line['CurTemp (Celsius)']
        json_sib = data_temp['data']['Temperature per module']
        for line in json_sib :
            modules = json_sib[line]
            for module in modules :
                if 'SIB' in module['Component'] :
                    sib_temps.append(module['CurTemp (Celsius)'])
                if 'ASIC' in module['Component'] :
                    asic_temps.append(module['CurTemp (Celsius)'])
    # SB7800 parsing 
    elif 'MGMT' in line : 
        for line in data_temp['data']['Temperature per module']['MGMT'] :
            if 'CPU package Sensor' in line['Component'] :
                cpu_temp = line['CurTemp (Celsius)']
            if 'SIB' in line['Component'] :
                sib_temps = line['CurTemp (Celsius)']
            if 'Ports AMB' in line['Component'] :
                asic_temps = line['CurTemp (Celsius)']

asic_temp_max = max(asic_temps)
sib_temp_max = max(sib_temps)
cpu_temp_max = cpu_temp

# calculate the use memory in percent
PercentUsed = (100 * Used) / Total

# return to icinga/nagios
Load_State = 'UNKNOWN'
Memory_State = 'UNKNOWN'
Module_State = 'OK'
Temp_State = 'UNKNOWN'

Load_Warning = re.split(r'\s*,\s*', Options.lwarning)
Load_Critical = re.split(r'\s*,\s*', Options.lcritical)
Temp_Warning = re.split(r'\s*,\s*', Options.twarning)
Temp_Critical = re.split(r'\s*,\s*', Options.tcritical)

### Global Tests 
# Test Memory
if PercentUsed >= Options.mcritical:
    Memory_State = 'CRITICAL'
elif PercentUsed >= Options.mwarning:
    Memory_State = 'WARNING'
else:
    Memory_State = 'OK'

# Test Load
if float(Load1) >= float(Load_Critical[0]) or float(Load5) >= float(Load_Critical[1]) or float(Load15) >= float(Load_Critical[2]):
    Load_State = 'CRITICAL'
elif float(Load1) >= float(Load_Warning[0]) or float(Load5) >= float(Load_Warning[1]) or float(Load15) >= float(Load_Warning[2]):
    Load_State = 'WARNING'
else:
    Load_State = 'OK'

# Test Temperature
if float(cpu_temp_max) >= float(Temp_Critical[0]) or float(asic_temp_max) >= float(Temp_Critical[1]) or float(sib_temp_max) >= float(Temp_Critical[2]):
    Temp_State = 'CRITICAL'
elif float(cpu_temp_max) >= float(Temp_Warning[0]) or float(asic_temp_max) >= float(Temp_Warning[1]) or float(sib_temp_max) >= float(Temp_Warning[2]):
    Temp_State = 'WARNING'
else:
    Temp_State = 'OK'

Message = '[PASSED] All Module(s) OK\n'
# Test Modules
if len(FailedModules) > 0:
    Message = '[FAILED] Found faulty Module(s): [' + ', '.join(FailedModules) + ']\n'
    Module_State = 'CRITICAL'
if len(MissingModules) < 0:
    # append message if CRIT
    if Module_State == 'CRITICAL':
        Message += '[FAILED] - Found missing Module(s) - [' + ', '.join(MissingModules) + ']\n'
    else:
        Message = '[FAILED] - Found missing Module(s): [' + ', '.join(MissingModules) + ']\n'
    Module_State = 'CRITICAL'

State = 'OK'
for status in [Memory_State,Load_State,Temp_State,Module_State] : 
    if 'WARNING' in status : 
        State = 'WARNING'
    if 'CRITICAL' in status : 
        State = 'CRITICAL'
        break
    
#print('Memory_State:{}'.format(Memory_State))
#print('Load_State:{}'.format(Load_State))
#print('Temp_State:{}'.format(Temp_State))
#print('Module_State:{}'.format(Module_State))
#print('State:{} \n'.format(State))

# Performances Data 
PerfData = []
PerfData.append('\'mem_used\'={}kb;;;0;{}'.format(Used, Total))
PerfData.append('\'load1\'={};{};{};0;'.format(str(Load1), Load_Warning[0], Load_Critical[0]))
PerfData.append('\'load5\'={};{};{};0;'.format(str(Load5), Load_Warning[1], Load_Critical[1]))
PerfData.append('\'load15\'={};{};{};0;'.format(str(Load15), Load_Warning[2], Load_Critical[2]))
PerfData.append('\'cpu\'={};{};{};;'.format(cpu_temp_max, Temp_Warning[0], Temp_Critical[0]))
PerfData.append('\'asic\'={};{};{};;'.format(asic_temp_max, Temp_Warning[1], Temp_Critical[1]))
PerfData.append('\'sib\'={};{};{};;'.format(sib_temp_max, Temp_Warning[2], Temp_Critical[2]))

# Message formating 
Message += 'Memory used: {}%%\n'.format(PercentUsed)
Message += 'CPU:{} Asic:{} SIB:{}\n'.format(cpu_temp_max, asic_temp_max, sib_temp_max)
if 'WARNING' in Load_State :
    Message += '[FAILED] - CPU Load: {},{},{}\n'.format(str(Load1), str(Load5), str(Load15))
elif 'CRITICAL' in Load_State :
    Message += '[FAILED] - CPU Load: {},{},{}\n'.format(str(Load1), str(Load5), str(Load15))
else :
    Message += '[PASSED] - CPU Load: {},{},{}\n'.format(str(Load1), str(Load5), str(Load15))

PrintAndExit(Message, PerfData, State)
