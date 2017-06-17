#!/usr/bin/env python

import signal
import logging
import logging.handlers
import os
import sys
import ConfigParser
import time
import atexit
from signal import SIGTERM
import MySQLdb as mdb
import dht11
import datetime
import httplib

import RPi.GPIO as GPIO  
from time import sleep  # this lets us have a time delay (see line 12)  
from distutils.fancy_getopt import fancy_getopt

ON = GPIO.LOW
OFF = GPIO.HIGH

dname = os.path.dirname(os.path.abspath(__file__))

# read values from the config file
config = ConfigParser.ConfigParser()
config.read(dname + "/config.txt")

LOG_LOGFILE = config.get('logging', 'logfile')
logLevelConfig = config.get('logging', 'loglevel')
if logLevelConfig == 'info': 
    LOG_LOGLEVEL = logging.INFO
elif logLevelConfig == 'warn':
    LOG_LOGLEVEL = logging.WARNING
elif logLevelConfig ==  'debug':
    LOG_LOGLEVEL = logging.DEBUG   

LOGROTATE = config.get('logging', 'logrotation')
LOGCOUNT = int(config.get('logging', 'logcount'))

logger = logging.getLogger(__name__)
logger.setLevel(LOG_LOGLEVEL)
handler = logging.handlers.TimedRotatingFileHandler(LOG_LOGFILE, when=LOGROTATE, backupCount=LOGCOUNT)
formatter = logging.Formatter('%(asctime)s %(levelname)-8s %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

class MyLogger(object):
        def __init__(self, logger, level):
                self.logger = logger
                self.level = level

        def write(self, message):
                # Only log if there is a message (not just a new line)
                if message.rstrip() != "":
                        self.logger.log(self.level, message.rstrip())

sys.stdout = MyLogger(logger, logging.INFO)
# sys.stderr = MyLogger(logger, logging.ERROR)

CONN_PARAMS = (config.get('main', 'mysqlHost'), config.get('main', 'mysqlUser'),
               config.get('main', 'mysqlPass'), config.get('main', 'mysqlDatabase'),
               int(config.get('main', 'mysqlPort')))

ORANGE_PIN = int(config.get('main', 'ORANGE_PIN'))
YELLOW_PIN = int(config.get('main', 'YELLOW_PIN'))
GREEN_PIN = int(config.get('main', 'GREEN_PIN'))
AUX_PIN = int(config.get('main', 'AUX_PIN'))
AUX_ID = int(config.get('main', 'AUX_ID'))

RELAY_CONNECTION = config.get('main', 'RELAY_CONNECTION')
REMOTE_RELAY_URL = config.get('main', 'REMOTE_RELAY_URL')
REMOTE_RELAY_KEY = config.get('main', 'REMOTE_RELAY_KEY')
ORANGE_UNC = config.get('main', 'ORANGE_UNC')
YELLOW_UNC = config.get('main', 'YELLOW_UNC')
GREEN_UNC = config.get('main', 'GREEN_UNC')
AUX_UNC = config.get('main', 'AUX_UNC')

INDOOR_SENSOR_PIN = int(config.get('main', 'INDOOR_SENSOR_PIN'))
SENSOR_RETRY_MAX = 5

ACTIVE_HYSTERESIS = float(config.get('main','active_hysteresis'))
INACTIVE_HYSTERESIS = float(config.get('main','inactive_hysteresis'))

DAEMON_STOPPED = 0
DAEMON_RUNNING = 1
DAEMON_STOPPING = 2

CHECK_FREQUENCY = int(config.get('main', 'SENSOR_CHECK_FREQUENCY'))  # seconds between checking temp

class HVACState():
    fan = OFF
    heat = OFF
    cool = OFF
    aux = OFF
    
    def __init__(self, fan, heat, cool, aux):
        self.fan = fan
        self.heat = heat
        self.cool = cool
        self.aux = aux
    
    def show(self):
        return 'fan %s, heat %s, cool %s, aux %s' % ('ON' if self.fan == ON else 'OFF', 'ON' if self.heat == ON else 'OFF', 'ON' if self.cool == ON else 'OFF', 'ON' if self.aux == ON else 'OFF')
    
class thermDaemon():
    _daemonStatus = DAEMON_STOPPED
    
    def getDBTargets(self):
        conDB = mdb.connect(CONN_PARAMS[0], CONN_PARAMS[1], CONN_PARAMS[2], CONN_PARAMS[3], port=CONN_PARAMS[4])
        cursor = conDB.cursor()
        
        cursor.execute("SELECT * from ThermostatSet")
        
        targs = cursor.fetchall()[0]
        
        cursor.close()
        conDB.close()
        return targs[:-1]
    
    def logStatus(self, mode, moduleID, targetTemp, actualTemp, hvacState):
        conDB = mdb.connect(CONN_PARAMS[0], CONN_PARAMS[1], CONN_PARAMS[2], CONN_PARAMS[3], port=CONN_PARAMS[4])
        cursor = conDB.cursor()

        cursor.execute("""INSERT ThermostatLog SET mode='%s', moduleID=%s, targetTemp=%s, actualTemp=%s,
                        coolOn=%s, heatOn=%s, fanOn=%s, auxOn=%s""" % 
                        (str(mode), str(moduleID), str(targetTemp), str(actualTemp),
                        str(hvacState.cool), str(hvacState.heat), str(hvacState.fan), str(hvacState.aux)))

        cursor.close()
        conDB.commit()
        conDB.close()
        
    def getTempList(self):
        conDB = mdb.connect(CONN_PARAMS[0], CONN_PARAMS[1], CONN_PARAMS[2], CONN_PARAMS[3], port=CONN_PARAMS[4])
        cursor = conDB.cursor()

        cursor.execute("SELECT MAX(moduleID) FROM ModuleInfo")
        totSensors = int(cursor.fetchall()[0][0])

        allModTemps = []
        for modID in range(totSensors):
            try:
                queryStr = ("SELECT * FROM SensorData WHERE moduleID=%s ORDER BY readingID DESC LIMIT 1" % str(modID + 1))
                cursor.execute(queryStr)
                allModTemps.append(float(cursor.fetchall()[0][4]))
            except:
                pass

        cursor.close()
        conDB.close()

        return allModTemps

    def getLocalTemp(self, sendToDB=False):
        result =  False
        temp_f = 0.0
        humid = 0.0
        
        try:
            sensor = dht11.DHT11(pin=INDOOR_SENSOR_PIN)
            sensorResult = sensor.read()
            retryCount = SENSOR_RETRY_MAX
            while retryCount > 0 and not sensorResult.is_valid():
                retryCount = retryCount - 1
                time.sleep(1)
                sensorResult = sensor.read()
                
            if sensorResult.is_valid():
                temp_f = sensorResult.temperature * 9.0 / 5.0 + 32.0
                humid = sensorResult.humidity * 1.0
                logger.debug("Temperature: %f C" % sensorResult.temperature)
                logger.debug("Humidity: %3.2f %%" % sensorResult.humidity)
        
                conDB = mdb.connect(CONN_PARAMS[0],CONN_PARAMS[1],CONN_PARAMS[2],CONN_PARAMS[3],port=CONN_PARAMS[4])
                cursor = conDB.cursor()
        
                query = "INSERT into SensorData (moduleID, location, temperature, humidity) VALUES (1, 'Local', %4.1f, %3.2f)" % (temp_f, humid)
                logger.debug(query)
                cursor.execute(query)
                
                cursor.close()
                conDB.commit()
                conDB.close()
                result = True
        except Exception, err:
            logger.debug(err)

            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            logger.error('1Error occurred at %s' % (datetime.datetime.now().strftime('%m-%d-%y-%X')))
            logger.error(str(exc_type.__name__))
            logger.error(str(fname))
            logger.error('Line '+ str(exc_tb.tb_lineno))
        
        return result
    
    def setHVAC(self, orange=OFF, yellow=OFF, green=OFF, aux=OFF):
        if (RELAY_CONNECTION == 'DIRECT'):
						logger.debug('before setting: heat %s, cool %s, fan %s, aux %s' % ('ON' if GPIO.input(ORANGE_PIN)==ON else 'OFF', 'ON' if GPIO.input(YELLOW_PIN)==ON else 'OFF', 'ON' if GPIO.input(GREEN_PIN)==ON else 'OFF', 'ON' if GPIO.input(AUX_PIN)==ON else 'OFF'))
				
						GPIO.output(ORANGE_PIN, orange)
						GPIO.output(YELLOW_PIN, yellow)
						GPIO.output(GREEN_PIN, green)
						GPIO.output(AUX_PIN, aux)
						logger.debug('after setting: heat %s, cool %s, fan %s, aux %s' % ('ON' if GPIO.input(ORANGE_PIN)==ON else 'OFF', 'ON' if GPIO.input(YELLOW_PIN)==ON else 'OFF', 'ON' if GPIO.input(GREEN_PIN)==ON else 'OFF', 'ON' if GPIO.input(AUX_PIN)==ON else 'OFF'))
        else:
				  conn = httplib.HTTPConnection(REMOTE_RELAY_URL);
				  conn.request("GET", "%s=%s?key=%s" % (ORANGE_UNC, ("off" if orange == OFF else "on"), REMOTE_RELAY_KEY))
				  res = conn.getresponse()
				  resdata = res.read()
				  logger.debug("setting orange: %s" % resdata)

				  conn.request("GET", "%s=%s?key=%s" % (YELLOW_UNC, ("off" if yellow == OFF else "on"), REMOTE_RELAY_KEY))
				  res = conn.getresponse()
				  resdata = res.read()
				  logger.debug("setting yellow: %s" % resdata)
				  
				  conn.request("GET", "%s=%s?key=%s" % (GREEN_UNC, ("off" if green == OFF else "on"), REMOTE_RELAY_KEY))
				  res = conn.getresponse()
				  resdata = res.read()
				  logger.debug("setting green: %s" % resdata)

				  conn.request("GET", "%s=%s?key=%s" % (AUX_UNC, ("off" if aux == OFF else "on"), REMOTE_RELAY_KEY))
				  res = conn.getresponse()
				  resdata = res.read()
				  logger.debug("setting aux: %s" % resdata)
				          
    def getHVACState(self):
        if (RELAY_CONNECTION == 'DIRECT'):
          return HVACState(GPIO.input(GREEN_PIN), GPIO.input(ORANGE_PIN), GPIO.input(YELLOW_PIN), GPIO.input(AUX_PIN))
        else:
				  logger.debug("Getting state")
				  state = None
				  try:
				    conn = httplib.HTTPConnection(REMOTE_RELAY_URL, 80, timeout=15)
				    if (conn != None):
				      conn.request("GET", "/all=state?key=%s" % (REMOTE_RELAY_KEY))
				      res = conn.getresponse()
				      state = res.read()
				  
				      logger.debug(state)
				  except httplib.HTTPException:
				    logger.debug("Getting HVAC State: HTTPException")
				  except httplib.ImproperConnectionState:
				    logger.debug("Getting HVAC State: ImproperConnectionState")
				  except Exception:
				    logger.debug("Getting HVAC State: General exception")
				    
				  if state != None and state != "":
				    states = state.split(',')
				    logger.debug(states)
				  else:
				    states = ["ON","ON","ON","ON"]
				    
				  #response is in order: Green, Orange, Yellow, Aux

				  return HVACState(OFF if states[0].rstrip() == "OFF" else ON, 
					       OFF if states[1].rstrip() == "OFF" else ON, 
					       OFF if states[2].rstrip() == "OFF" else ON, 
					       OFF if states[3].rstrip() == "OFF" else ON)
          
    def fanOnly(self):
        #Turn the fan on
        self.setHVAC(OFF, OFF, ON, OFF)
    
    def cool(self):
        #Set cooling mode
        self.setHVAC(OFF, ON, ON, OFF)
        
    def heat(self):
        self.setHVAC(ON, OFF, ON, OFF)
            
    def idle(self):
        self.setHVAC(OFF, OFF, OFF, OFF)        

    def heatMode(self, moduleID, tempList, hvacState, targetTemp):
        logger.debug('Heat mode')
        if hvacState.fan==OFF and hvacState.heat==OFF and hvacState.cool==OFF and hvacState.aux==OFF: # system is idle/off
            logger.debug('system is off')
            if tempList[moduleID-1] < targetTemp - INACTIVE_HYSTERESIS: #temp < target = turn on heat
                logger.debug('turning on heat')
                self.heat()
        elif hvacState.fan==ON and hvacState.heat==ON: #system is heating
            logger.debug('system is heating')
            if tempList[moduleID-1] > targetTemp + ACTIVE_HYSTERESIS: #temp has been satisfied
                logger.debug('turning off heat. going to fan mode')
                #go to fan-only mode
                self.fanOnly()
                sleep(30)
                #go to idle mode
                logger.debug('finishing turning the heat off. turning fan off.')
        elif hvacState.fan==ON and hvacState.cool==ON: #system is cooling
            logger.debug('system is cooling')
            if tempList[moduleID-1] < targetTemp - ACTIVE_HYSTERESIS: #temp is low so change from cooling to heat
                #go to idle mode
                self.idle()
                logger.debug('switching from cool to heat. turning off for a short time')
                sleep(30)
                #turn heat on
                logger.debug('finishing switch from cool to heat. turning on heat')
                self.heat()
            else:
                #go to idle mode
                logger.debug('temp is satisfied. turning system off')
                self.idle()
        elif hvacState.fan==ON and hvacState.cool==OFF and hvacState.heat==OFF: #fan-only mode
            logger.debug('fan only mode')
            if tempList[moduleID-1] < targetTemp - INACTIVE_HYSTERESIS: #temp is low so turn heat on
                logger.debug('turning heat on')
                self.heat()
            else:
                logger.debug('turning fan off')
                self.idle()
        elif hvacState.fan==OFF and (hvacState.cool==ON or hvacState.heat==ON): #no fan but heating or cooling - error
            logger.debug('fan not running when it should')
            #turn off
            self.idle()
        
    def coolMode(self, moduleID, tempList, hvacState, targetTemp):
        logger.debug('Cool mode')
        if hvacState.fan==OFF and hvacState.heat==OFF and  hvacState.cool==OFF and hvacState.aux==OFF: # system is idle/off
            logger.debug('system is off')
            if tempList[moduleID-1] > targetTemp + INACTIVE_HYSTERESIS: #temp > target = turn on a/c
                logger.debug('turning on a/c')
                self.cool()
        elif hvacState.fan==ON and hvacState.heat==ON: #system is heating
            logger.debug('system is heating')
            if tempList[moduleID-1] > targetTemp + ACTIVE_HYSTERESIS: #temp > target = turn on a/c
                logger.debug('finishing turning the heat off. turning cool on')
                #go to cool mode
                self.cool()
        elif hvacState.fan==ON and hvacState.cool==ON: #system is cooling
            logger.debug('system is cooling')
            if tempList[moduleID-1] < targetTemp - ACTIVE_HYSTERESIS: #temp is satisfied so turn off a/c
                logger.debug('turning off cool. running fan-only first.')
                self.fanOnly()
                sleep(30)
                #go to idle mode
                logger.debug('finishing. turning off fan')
                self.idle()
        elif hvacState.fan==ON and hvacState.cool==OFF and hvacState.heat==OFF: #fan-only mode
            logger.debug('fan only mode')
            if tempList[moduleID-1] > targetTemp + INACTIVE_HYSTERESIS: #temp is high so turn a/c
                logger.debug('turning cool on')
                self.cool()
            else:
                logger.debug('turning fan off')
                self.idle()
        elif hvacState.fan==OFF and (hvacState.cool==ON or hvacState.heat==ON): #no fan but heating or cooling - error
            logger.debug('fan not running when it should')
            #turn off
            self.idle()
        
    def idleMode(self, moduleID, tempList, hvacState, targetTemp):
        logger.debug('Idle mode. turning off')
        self.idle()

    def fanMode(self, moduleID, tempList, hvacState, targetTemp):
        logger.debug('Fan mode')
        self.fanOnly()
        
    def configIO(self):
        if (RELAY_CONNECTION == 'DIRECT'):
					GPIO.setwarnings(False)
					GPIO.setmode(GPIO.BCM)  # set up BCM GPIO numbering
				
					GPIO.setup(ORANGE_PIN, GPIO.OUT)
					GPIO.setup(YELLOW_PIN, GPIO.OUT)
					GPIO.setup(GREEN_PIN, GPIO.OUT)
					GPIO.setup(AUX_PIN, GPIO.OUT)
    
    def testDatabaseConnection(self):
        retry  = 30
        test = None
        while test == None and retry > 0:
            logger.info('Connecting to database at %s'%(datetime.datetime.now().strftime('%m-%d-%y-%X')))
            try:
              test = mdb.connect(CONN_PARAMS[0], CONN_PARAMS[1], CONN_PARAMS[2], CONN_PARAMS[3], port=CONN_PARAMS[4])
            except Exception:
              logger.info('Failed at %s \n'%(datetime.datetime.now().strftime('%m-%d-%y-%X')))
            else:
              logger.info('Succeeded at %s \n'%(datetime.datetime.now().strftime('%m-%d-%y-%X')))
              test.close();
            retry = retry - 1 
            if test == None:
                sleep(5)
                 

    def run(self):
        logger.info("Thermostat Control Starting")
        
        self._daemonStatus = DAEMON_RUNNING
        
        self.testDatabaseConnection() 

        try:
            lastCheck = time.time()  # last time the aux temp was checked
            activeMode = 'Off'
        
            self.configIO()
                
            while self._daemonStatus == DAEMON_RUNNING:
                now = time.time()
                lastCheckElapsed = now - lastCheck  # how long since last temp check
                hvacState = self.getHVACState()

                setTime, moduleID, targetTemp, targetMode, expiryTime = self.getDBTargets()
                
                moduleID = int(moduleID)
                targetTemp = int(targetTemp)
                tempList = self.getTempList()
               
                #Periodically, check the indoor temperature
                if lastCheckElapsed > CHECK_FREQUENCY:
                    logger.debug("Getting local temperature")
                    self.getLocalTemp(True)  # get the indoor temp and save it to the database
                    self.logStatus(activeMode, moduleID, targetTemp, tempList[moduleID - 1], hvacState)
                    lastCheck = now
                
                #Depending on the mode, HVAC state, and the difference between the desired temp and current temp, turn HVAC on or off
                logger.debug('Operating mode is %s' % targetMode)
                
                #Get the last temp reading
                tempList = self.getTempList()
                
                logger.debug('Pin Value State:' + hvacState.show())
                logger.debug('Target Mode:' + targetMode)
                logger.debug('Actual Mode:' + activeMode)
                logger.debug('Temp from DB:'+str(tempList))
                logger.debug('Target Temp:'+str(targetTemp))

                logger.debug('Target Mode: %s' % targetMode)
                if targetMode == 'Heat':
                    self.heatMode(moduleID, tempList, hvacState, targetTemp)
                    activeMode = 'Heat'
                elif targetMode == 'Cool':
                    self.coolMode(moduleID, tempList, hvacState, targetTemp)
                    activeMode = 'Cool'
                elif targetMode == 'Fan':
                    self.fanMode(moduleID, tempList, hvacState, targetTemp)
                    activeMode = 'Fan'
                elif targetMode == 'Off':
                    self.idleMode(moduleID, tempList, hvacState, targetTemp)
                    activeMode = 'Off'
                else:
                    logger.info('Invalid Target Mode %s' % targetMode)
                    
                sleep(5)
            
        except Exception, err:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            logger.error(err)
            logger.error('Line ' +  str(exc_tb.tb_lineno))
            logger.error('Error occurred at %s'%(datetime.datetime.now().strftime('%m-%d-%y-%X')))
            logger.error(str(exc_type.__name__))
            logger.error(str(fname))
            logger.error('Line '+ str(exc_tb.tb_lineno)) 

        except KeyboardInterrupt:
            logger.info('Keyboard interrupt')
        finally:
            self.idle()
            if (RELAY_CONNECTION == 'DIRECT'):
              GPIO.cleanup()
            self._daemonStatus = DAEMON_STOPPED
        
def sigterm_handler(_signo, _stack_frame):
    "When sysvinit sends the TERM signal, cleanup before exiting."
    logger.info("Received signal {}, exiting...".format(_signo))
    print("Received signal {}, exiting...".format(_signo))
    logger.info("Stopping Daemon due to signal")
    if (RELAY_CONNECTION == 'DIRECT'):
      GPIO.cleanup()
    sys.exit(0)

signal.signal(signal.SIGTERM, sigterm_handler)

logger.debug("Starting Daemon")

thermy = thermDaemon()
thermy.run()
logger.debug("Stopping Daemon")
