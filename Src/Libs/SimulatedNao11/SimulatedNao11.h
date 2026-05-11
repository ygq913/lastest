/**
 * @file SimulatedNao11/SimulatedNao11.h
 *
 * This file declares the 11-player simulation controller.
 * This is a placeholder for 11-a-side simulation extensions.
 */

#pragma once

#include "SimulatedNao/ConsoleRoboCupCtrl.h"

/**
 * The class implements the SimRobot controller for 11-a-side RoboCup games.
 */
class SimulatedNao11 : public ConsoleRoboCupCtrl
{
public:
  /**
   * @param application The interface to SimRobot.
   */
  SimulatedNao11(SimRobot::Application& application) : ConsoleRoboCupCtrl(application) {}
};
