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
import requests
import mysql.connector
from mysql.connector import pooling

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

#CONN_PARAMS = (config.get('main', 'mysqlHost'), config.get('main', 'mysqlUser'),
#               config.get('main', 'mysqlPass'), config.get('main', 'mysqlDatabase'),
#               int(config.get('main', 'mysqlPort')))

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
    
class ThermError(Exception):
  pass
class ThermDatabaseError(ThermError):
  def __init__(self, message):
    self.message = message
    
class ThermDatabase():
  _dbconfig = None
  _pool = None
  _logger = None
  
  def __init__(self, logger):
    self._dbconfig = {
      "database" : config.get('main', 'mysqlDatabase'),
      "host" : config.get('main', 'mysqlHost'),
      "user" : config.get('main', 'mysqlUser'),
      "password" : config.get('main', 'mysqlPass'), 
      "port" : int(config.get('main', 'mysqlPort'))	
    }
    self._logger = logger
  
  def connect(self):
    result = False
    if (self._pool == None):
      try:
        self._pool = mysql.connector.pooling.MySQLConnectionPool(pool_name="thermy", pool_size=3, **self._dbconfig)
        result = True
      except mdb.Error as err:
        self._logger.error("Database connect failed: %s" % (err))
      
    else:
      self._logger.warning("Database connect failed. Database already connected")
      result = True
      
    return result
    
  def getConnection(self):
    result = None
    if (self._pool != None):
      try:
        result = self._pool.get_connection()
      except mdb.Error as err:
        self._logger.error("Database pool allocation t failed: %s" % (err))
    else:
      self._logger.error("Unable to get database connection. Connect to database before requesting a pooled connection.")
    
    return result
    
  def getCursor(self, connection):
    result = None
    if (self._pool != None):
      if (connection != None):
        try:
          result = connection.cursor()
        except mdb.Error as err:
          self._logger.error("getCursor failed: %s" % (err))
      else:
        self._logger.error("Unable to get database connection. Connect to database before requesting a pooled connection.")
    else:
      self._logger.error("Unable to get database connection. Connect to database before requesting a pooled connection.")
      
    return result    
      
class thermDaemon():
    _daemonStatus = DAEMON_STOPPED
    db = None
    
    def __init__(self):
      self.db = ThermDatabase(logger)
      self.db.connect()
    
    def getDBTargets(self):
        result = [None,None,None,None,None,None]
        conDB = self.db.getConnection()
        if (conDB != None):
          cursor = self.db.getCursor(conDB)

          if (cursor != None):        
            cursor.execute("SELECT timeStamp, moduleID, targetTemp, targetMode, expiryTime, entryNo from ThermostatSet")
        
            targs = cursor.fetchall()[0]
        
            cursor.close()
            
            result = targs[:-1]
            
          conDB.close()
        return result
    
    def logStatus(self, mode, moduleID, targetTemp, actualTemp, hvacState):
        conDB = self.db.getConnection()
        if (conDB != None):
          cursor = self.db.getCursor(conDB)
          
          if (cursor != None):
            try:
              cursor.execute("""INSERT ThermostatLog SET mode='%s', moduleID=%s, targetTemp=%s, actualTemp=%s,
                              coolOn=%s, heatOn=%s, fanOn=%s, auxOn=%s""" % 
                              (str(mode), str(moduleID), str(targetTemp), str(actualTemp),
                              str(hvacState.cool), str(hvacState.heat), str(hvacState.fan), str(hvacState.aux)))

              cursor.close()
            except Exception as err:
              logger.error("logStatus. Unable to log to database: %s" % (err))
            conDB.commit()
          conDB.close()
        
    def getTempList(self):
        logger.debug("start temp list")
        result = []
        sensors = None
        readings = None
        conDB = self.db.getConnection()
        if (conDB != None):
          cursor = self.db.getCursor(conDB)
          if (cursor != None):
            try:
              cursor.execute("SELECT moduleID, strDescription, firmwareVer, tempSense, humiditySense, lightSense, motionSense FROM ModuleInfo WHERE moduleID != 0 ORDER BY moduleID") # Get all modules except the outdoor weather
              sensors = cursor.fetchall()
            except Exception as sensorErr:
              logger.error("getTempList. Unable to get sensors. %s" % (sensorErr))
            cursor.close()
          else:
            logger.error("getTempList. Unable to get sensor cursor.")
          
          if sensors != None:
            cursor = self.db.getCursor(conDB)
            if (cursor != None):
              for sensor in sensors:
                try:
                  cursor.execute("SELECT readingID, timeStamp, location, temperature, humidity, light, occupied FROM SensorData WHERE moduleID=%s ORDER BY timeStamp DESC LIMIT 1" % sensor[0])
                  readings = cursor.fetchall()
                
                  result.append([sensor[0], readings[0][1], readings[0][2], readings[0][3], readings[0][4]])
                  
                except Exception as readingsErr:
                  logger.error("getTempList. Unable to get readings. %s" % (readingsErr))
              cursor.close()
          else:
            logger.error("getTempList. Unable to get sensor cursor")
          conDB.close()
          
          logger.debug("complete temp list")
        return result
        
    def getLastReading(self, moduleID):
        conDB = self.db.getConnection()
        if (conDB != None):
          cursor = self.db.getCursor(conDB)
          if (cursor != None):
            try:
              cursor.execute("SELECT MAX(timeStamp) FROM SensorData WHERE moduleID=%s" % (moduleID))
              stamps = cursor.fetchall()
            except Exception as err:
              logger.error("getLastReading. Unable to get last reading: %s" % (err))  

            cursor.close()
          conDB.close()

        return stamps[0][0]

    def setDefaultModule(self, moduleID):
        conDB = self.db.getConnection()
        if (conDB != None):
          cursor = self.db.getCursor(conDB)
          if (cursor != None):
            try:
              cursor.execute("UPDATE ThermostatSet SET moduleID=%d" % (moduleID))
              conDB.commit()
            except Exception as err:
              logger.error("setDefaultMode. Unable to update database: %s" % (err))
            cursor.close()
          conDB.close()
        return

    def setHVAC(self, orange=OFF, yellow=OFF, green=OFF, aux=OFF):
        if (RELAY_CONNECTION == 'DIRECT'):
						logger.debug('before setting: heat %s, cool %s, fan %s, aux %s' % ('ON' if GPIO.input(ORANGE_PIN)==ON else 'OFF', 'ON' if GPIO.input(YELLOW_PIN)==ON else 'OFF', 'ON' if GPIO.input(GREEN_PIN)==ON else 'OFF', 'ON' if GPIO.input(AUX_PIN)==ON else 'OFF'))
				
						GPIO.output(ORANGE_PIN, orange)
						GPIO.output(YELLOW_PIN, yellow)
						GPIO.output(GREEN_PIN, green)
						GPIO.output(AUX_PIN, aux)
						logger.debug('after setting: heat %s, cool %s, fan %s, aux %s' % ('ON' if GPIO.input(ORANGE_PIN)==ON else 'OFF', 'ON' if GPIO.input(YELLOW_PIN)==ON else 'OFF', 'ON' if GPIO.input(GREEN_PIN)==ON else 'OFF', 'ON' if GPIO.input(AUX_PIN)==ON else 'OFF'))
        else:
 				    payload = {'key' : REMOTE_RELAY_KEY, 'ts' : int(round(time.time() * 1000))}
 				    url = "HTTP://%s" % (REMOTE_RELAY_URL)
 				    try:
 				      # build request string
 				      command = "/orange=%s/yellow=%s/green=%s/aux=%s" % (("off" if orange == OFF else "on"),("off" if yellow == OFF else "on"),("off" if green == OFF else "on"),("off" if aux == OFF else "on"))
 				      r = requests.get("%s%s" % (url, command), timeout=10, params=payload)
				    except requests.exceptions.ConnectionError as e:
				      logger.error("Setting relay state: ConnectionError. %s" % e)
				    except requests.exceptions.HTTPError as e:
				      logger.error("Setting relay state: HTTPError. %s" % e)
				    except requests.exceptions.URLRequired as e:
				      logger.error("Setting relay state: URLRequired. %s" % e)
				    except requests.exceptions.TooManyRedirects as e:
				      logger.error("Setting relay state: TooManyRedirects. %s" % e)
				    except requests.exceptions.ConnectTimeout as e:
				      logger.error("Setting relay state: ConnectTimeout. %s" % e)
				    except requests.exceptions.ReadTimeout as e:
				      logger.error("Setting relay state: ReadTimeout. %s" % e)
				    except requests.exceptions.Timeout as e:
				      logger.error("Setting relay state: Timeout. %s" % e)
				    except requests.exceptions.RequestException as e:
				      logger.error("Setting relay state: RequestException. %s" % e)
				   
    def updateControllerStatus(self):
        conDB = self.db.getConnection()
        if (conDB != None):
          cursor = self.db.getCursor(conDB)
          if (cursor != None):
            try:
              cursor.execute("INSERT INTO ControllerStatus (lastStatus) values (NOW())")
              cursor.close()
              conDB.commit()
            except Exception as err:
              logger.error("updateControllerStatus. Unable to update database: %s" % (err))

          conDB.close()
		    
    def getHVACState(self):
        if (RELAY_CONNECTION == 'DIRECT'):
          return HVACState(GPIO.input(GREEN_PIN), GPIO.input(ORANGE_PIN), GPIO.input(YELLOW_PIN), GPIO.input(AUX_PIN))
        else:
				  logger.debug("Getting state")
				  state = None
				  r = None
				  try:
				    payload = {'key' : REMOTE_RELAY_KEY, 'ts' : int(round(time.time() * 1000))}
				    r = requests.get("HTTP://%s/all=state" % (REMOTE_RELAY_URL), timeout=10, params=payload, stream=True)
				    state = r.text
				    
				    logger.debug("Get State Status Code %s " % (r.status_code))
				    logger.debug("Get State text %s " % (r.text))
				    
				  except requests.exceptions.ConnectionError as e:
				    logger.error("Getting relay state: ConnectionError. %s" % e)
				  except requests.exceptions.HTTPError as e:
				    logger.error("Getting relay state: HTTPError. %s" % e)
				  except requests.exceptions.URLRequired as e:
				    logger.error("Getting relay state: URLRequired. %s" % e)
				  except requests.exceptions.TooManyRedirects as e:
				    logger.error("Getting relay state: TooManyRedirects. %s" % e)
				  except requests.exceptions.ConnectTimeout as e:
				    logger.error("Getting relay state: ConnectTimeout. %s" % e)
				  except requests.exceptions.ReadTimeout as e:
				    logger.error("Getting relay state: ReadTimeout. %s" % e)
				  except requests.exceptions.Timeout as e:
				    logger.error("Getting relay state: Timeout. %s" % e)
				  except requests.exceptions.RequestException as e:
				    logger.error("Getting relay state: RequestException. %s" % e)
				  
				    
				  if r != None and r.status_code == requests.codes.ok and state != None and state != "":
				    self.updateControllerStatus()
				    state = state.strip();
				    state = state.rstrip();
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

    def heatMode(self, currentTemp, hvacState, targetTemp):
        logger.debug('Heat mode')
        
        if currentTemp != None:
          if hvacState.fan==OFF and hvacState.heat==OFF and hvacState.cool==OFF and hvacState.aux==OFF: # system is idle/off
              logger.debug('system is off')
              if currentTemp < targetTemp - INACTIVE_HYSTERESIS: #temp < target = turn on heat
                  logger.debug('turning on heat')
                  self.heat()
          elif hvacState.fan==ON and hvacState.heat==ON: #system is heating
              logger.debug('system is heating')
              if currentTemp > targetTemp + ACTIVE_HYSTERESIS: #temp has been satisfied
                  logger.debug('turning off heat. going to fan mode')
                  #go to fan-only mode
                  self.fanOnly()
                  sleep(30)
                  #go to idle mode
                  logger.debug('finishing turning the heat off. turning fan off.')
          elif hvacState.fan==ON and hvacState.cool==ON: #system is cooling
              logger.debug('system is cooling')
              if currentTemp < targetTemp - ACTIVE_HYSTERESIS: #temp is low so change from cooling to heat
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
              if currentTemp < targetTemp - INACTIVE_HYSTERESIS: #temp is low so turn heat on
                  logger.debug('turning heat on')
                  self.heat()
              else:
                  logger.debug('turning fan off')
                  self.idle()
          elif hvacState.fan==OFF and (hvacState.cool==ON or hvacState.heat==ON): #no fan but heating or cooling - error
              logger.debug('fan not running when it should')
              #turn off
              self.idle()
        
    def coolMode(self, currentTemp, hvacState, targetTemp):
        logger.debug('Cool mode')
        
        if currentTemp != None:
          if hvacState.fan==OFF and hvacState.heat==OFF and  hvacState.cool==OFF and hvacState.aux==OFF: # system is idle/off
              logger.debug('system is off')
              if currentTemp > targetTemp + INACTIVE_HYSTERESIS: #temp > target = turn on a/c
                  logger.debug('turning on a/c')
                  self.cool()
          elif hvacState.fan==ON and hvacState.heat==ON: #system is heating
              logger.debug('system is heating')
              if currentTemp > targetTemp + ACTIVE_HYSTERESIS: #temp > target = turn on a/c
                  logger.debug('finishing turning the heat off. turning cool on')
                  #go to cool mode
                  self.cool()
          elif hvacState.fan==ON and hvacState.cool==ON: #system is cooling
              logger.debug('system is cooling')
              if currentTemp < targetTemp - ACTIVE_HYSTERESIS: #temp is satisfied so turn off a/c
                  logger.debug('turning off cool. running fan-only first.')
                  self.fanOnly()
                  sleep(30)
                  #go to idle mode
                  logger.debug('finishing. turning off fan')
                  self.idle()
          elif hvacState.fan==ON and hvacState.cool==OFF and hvacState.heat==OFF: #fan-only mode
              logger.debug('fan only mode')
              if currentTemp > targetTemp + INACTIVE_HYSTERESIS: #temp is high so turn a/c
                  logger.debug('turning cool on')
                  self.cool()
              else:
                  logger.debug('turning fan off')
                  self.idle()
          elif hvacState.fan==OFF and (hvacState.cool==ON or hvacState.heat==ON): #no fan but heating or cooling - error
              logger.debug('fan not running when it should')
              #turn off
              self.idle()
          
    def idleMode(self):
        logger.debug('Idle mode. turning off')
        self.idle()

    def fanMode(self):
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
              test = self.db.getConnection()
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
            activeMode = 'Off'
        
            self.configIO()
                
            while self._daemonStatus == DAEMON_RUNNING:
                now = time.time()
                hvacState = self.getHVACState()

                setTime, moduleID, targetTemp, targetMode, expiryTime = self.getDBTargets()
                
                #Check when the last reading was from the target module. If it's been too long, switch 
                #to the default local module
                lastReading = self.getLastReading(moduleID)
                now = datetime.datetime.now()
                diff = now - lastReading
                if (diff.seconds > 600):  # more than 600 seconds (10 minutes) has passed since last reading so default back to the local sensor
                  logger.debug("No reading from module %d. Changing to default module" % (moduleID))
                  moduleID = 1
                  self.setDefaultModule(moduleID)
                
                moduleID = int(moduleID)
                targetTemp = int(targetTemp)
               
                #Depending on the mode, HVAC state, and the difference between the desired temp and current temp, turn HVAC on or off
                logger.debug('Operating mode is %s' % targetMode)
                
                #Get the last temp reading
                tempList = self.getTempList()
                
                logger.debug('Pin Value State:' + hvacState.show())
                logger.debug('Target Mode:' + targetMode)
                logger.debug('Actual Mode:' + activeMode)
                logger.debug('Temp from DB:'+str(tempList))
                logger.debug('Target Temp:'+str(targetTemp))
                logger.debug('moduleID:'+str(moduleID))
                logger.debug('Target Mode: %s' % targetMode)
                
                #identify the readings for the sensor that we're using to control from
                sensorReading = None
                for temp in tempList:
                  if (temp[0] == moduleID):
                    sensorReading = temp
                    break
                
                if (sensorReading == None):  # default to the local sensor
                  for temp in tempList:
                    if (temp[0] == 1):
                      sensorReading = temp
                      break
                
                logger.debug('Current Temp:'+str(sensorReading[3]))
                if targetMode == 'Heat':
                    self.heatMode(sensorReading[3] if sensorReading != None else None, hvacState, targetTemp)
                    activeMode = 'Heat'
                elif targetMode == 'Cool':
                    self.coolMode(sensorReading[3] if sensorReading != None else None, hvacState, targetTemp)
                    activeMode = 'Cool'
                elif targetMode == 'Fan':
                    self.fanMode()
                    activeMode = 'Fan'
                elif targetMode == 'Off':
                    self.idleMode()
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
