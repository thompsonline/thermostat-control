-- phpMyAdmin SQL Dump
-- version 4.2.12deb2+deb8u2
-- http://www.phpmyadmin.net
--
-- Host: localhost
-- Generation Time: Jan 28, 2017 at 09:49 PM
-- Server version: 5.5.53-0+deb8u1
-- PHP Version: 5.6.29-0+deb8u1

SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";
SET time_zone = "+00:00";


/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8 */;

--
-- Database: `Thermostat`
--

-- --------------------------------------------------------

--
-- Table structure for table `ManualProgram`
--

CREATE TABLE `ManualProgram` (
`rowKey` int(11) unsigned NOT NULL,
  `weekDay` char(3) NOT NULL DEFAULT '',
  `time` time NOT NULL,
  `moduleID` int(11) unsigned NOT NULL,
  `desiredTemp` int(4) NOT NULL,
  `desiredMode` varchar(45) NOT NULL DEFAULT ''
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

-- --------------------------------------------------------

--
-- Table structure for table `ModuleInfo`
--

CREATE TABLE `ModuleInfo` (
`moduleID` int(11) unsigned,
  `strDescription` varchar(45) DEFAULT NULL,
  `firmwareVer` char(11) DEFAULT NULL,
  `tempSense` tinyint(1) NOT NULL DEFAULT '0',
  `humiditySense` tinyint(1) NOT NULL DEFAULT '0',
  `lightSense` tinyint(1) NOT NULL DEFAULT '0',
  `motionSense` tinyint(1) NOT NULL DEFAULT '0'
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

-- --------------------------------------------------------

--
-- Table structure for table `OperationModes`
--

CREATE TABLE IF NOT EXISTS `OperationModes` (
  `mode` varchar(45) NOT NULL DEFAULT '',
  `displayorder` tinyint(4) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

INSERT INTO `OperationModes` (`mode`, `displayorder`) VALUES
('Off', 0),
('Heat', 1),
('Cool', 2),
('Fan', 3);

-- --------------------------------------------------------

--
-- Table structure for table `ProgramTypes`
--

CREATE TABLE `ProgramTypes` (
  `program` varchar(45) NOT NULL DEFAULT '',
  `active` tinyint(1) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

-- --------------------------------------------------------

--
-- Table structure for table `SensorData`
--

CREATE TABLE `SensorData` (
`readingID` int(11) NOT NULL,
  `timeStamp` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `moduleID` int(11) unsigned NOT NULL,
  `location` varchar(25) NOT NULL,
  `temperature` decimal(4,1) NOT NULL,
  `humidity` decimal(4,2) DEFAULT NULL,
  `light` decimal(3,2) DEFAULT NULL,
  `occupied` tinyint(1) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

-- --------------------------------------------------------

--
-- Table structure for table `SmartProgram`
--

CREATE TABLE `SmartProgram` (
  `weekDay` char(3) NOT NULL DEFAULT '',
  `time` time NOT NULL,
  `moduleID` int(11) unsigned NOT NULL,
  `desiredTemp` int(4) NOT NULL,
  `desiredMode` varchar(45) NOT NULL DEFAULT ''
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

-- --------------------------------------------------------

--
-- Table structure for table `ThermostatLog`
--

CREATE TABLE `ThermostatLog` (
  `timeStamp` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `mode` varchar(45) NOT NULL DEFAULT '',
  `moduleID` int(11) unsigned NOT NULL,
  `targetTemp` int(11) DEFAULT NULL,
  `actualTemp` float DEFAULT NULL,
  `coolOn` tinyint(1) NOT NULL,
  `heatOn` tinyint(1) NOT NULL,
  `fanOn` tinyint(1) NOT NULL,
  `auxOn` tinyint(1) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

-- --------------------------------------------------------

--
-- Table structure for table `ThermostatSet`
--

CREATE TABLE `ThermostatSet` (
  `timeStamp` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `moduleID` int(11) unsigned NOT NULL,
  `targetTemp` int(11) NOT NULL,
  `targetMode` varchar(45) NOT NULL,
  `expiryTime` datetime NOT NULL,
`entryNo` int(11) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

--
-- Indexes for dumped tables
--

--
-- Indexes for table `ManualProgram`
--
ALTER TABLE `ManualProgram`
 ADD PRIMARY KEY (`rowKey`), ADD KEY `moduleID` (`moduleID`), ADD KEY `desiredMode` (`desiredMode`);

--
-- Indexes for table `ModuleInfo`
--
ALTER TABLE `ModuleInfo`
 ADD PRIMARY KEY (`moduleID`);

--
-- Indexes for table `OperationModes`
--
ALTER TABLE `OperationModes`
 ADD PRIMARY KEY (`mode`), ADD KEY `displayorder` (`displayorder`);

--
-- Indexes for table `ProgramTypes`
--
ALTER TABLE `ProgramTypes`
 ADD PRIMARY KEY (`program`);

--
-- Indexes for table `SensorData`
--
ALTER TABLE `SensorData`
 ADD PRIMARY KEY (`readingID`), ADD KEY `moduleID` (`moduleID`);

--
-- Indexes for table `SmartProgram`
--
ALTER TABLE `SmartProgram`
 ADD PRIMARY KEY (`weekDay`,`time`), ADD KEY `moduleID` (`moduleID`);

--
-- Indexes for table `ThermostatLog`
--
ALTER TABLE `ThermostatLog`
 ADD PRIMARY KEY (`timeStamp`), ADD KEY `moduleID` (`moduleID`), ADD KEY `mode` (`mode`);

--
-- Indexes for table `ThermostatSet`
--
ALTER TABLE `ThermostatSet`
 ADD PRIMARY KEY (`entryNo`), ADD KEY `moduleID` (`moduleID`);

--
-- AUTO_INCREMENT for dumped tables
--

--
-- AUTO_INCREMENT for table `ManualProgram`
--
ALTER TABLE `ManualProgram`
MODIFY `rowKey` int(11) unsigned NOT NULL AUTO_INCREMENT;
--
-- AUTO_INCREMENT for table `ModuleInfo`
--
ALTER TABLE `ModuleInfo`
MODIFY `moduleID` int(11) unsigned NOT NULL AUTO_INCREMENT;
--
-- AUTO_INCREMENT for table `SensorData`
--
ALTER TABLE `SensorData`
MODIFY `readingID` int(11) NOT NULL AUTO_INCREMENT;
--
-- AUTO_INCREMENT for table `ThermostatSet`
--
ALTER TABLE `ThermostatSet`
MODIFY `entryNo` int(11) NOT NULL AUTO_INCREMENT;
--
-- Constraints for dumped tables
--

--
-- Constraints for table `ManualProgram`
--
ALTER TABLE `ManualProgram`
ADD CONSTRAINT `ManualProgram_ibfk_1` FOREIGN KEY (`moduleID`) REFERENCES `ModuleInfo` (`moduleID`) ON DELETE CASCADE,
ADD CONSTRAINT `ManualProgram_ibfk_2` FOREIGN KEY (`desiredMode`) REFERENCES `OperationModes` (`mode`) ON DELETE NO ACTION;

--
-- Constraints for table `SensorData`
--
ALTER TABLE `SensorData`
ADD CONSTRAINT `SensorData_ibfk_1` FOREIGN KEY (`moduleID`) REFERENCES `ModuleInfo` (`moduleID`);

--
-- Constraints for table `SmartProgram`
--
ALTER TABLE `SmartProgram`
ADD CONSTRAINT `SmartProgram_ibfk_1` FOREIGN KEY (`moduleID`) REFERENCES `ModuleInfo` (`moduleID`) ON DELETE CASCADE;

--
-- Constraints for table `ThermostatLog`
--
ALTER TABLE `ThermostatLog`
ADD CONSTRAINT `ThermostatLog_ibfk_1` FOREIGN KEY (`moduleID`) REFERENCES `ModuleInfo` (`moduleID`) ON DELETE CASCADE,
ADD CONSTRAINT `ThermostatLog_ibfk_2` FOREIGN KEY (`mode`) REFERENCES `OperationModes` (`mode`) ON DELETE CASCADE;

--
-- Constraints for table `ThermostatSet`
--
ALTER TABLE `ThermostatSet`
ADD CONSTRAINT `ThermostatSet_ibfk_1` FOREIGN KEY (`moduleID`) REFERENCES `ModuleInfo` (`moduleID`);

/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;


CREATE TABLE IF NOT EXISTS `ControllerStatus` (
`id` int(11) NOT NULL,
  `lastStatus` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=latin1;

ALTER TABLE `ControllerStatus`
 ADD UNIQUE KEY `id` (`id`);

ALTER TABLE `ControllerStatus`
MODIFY `id` int(11) NOT NULL AUTO_INCREMENT,AUTO_INCREMENT=3;
