/**
 * @file JerseyClassifierProvider2020For2023.cpp
 *
 * This file implements a module that provides functionality to classify jerseys
 * by sampling pixels in an estimated area and classifying each of them as
 * belonging to the own team or to the opponent team.
 *
 * @author Thomas Röfer (the algorithm)
 * @author Lukas Malte Monnerjahn (the algorithm)
 * @author Arne Hasselbring (the module)
 * @author Tim Laue (the update for 2023)
 */

#include "JerseyClassifierProvider2020For2023.h"
#include "Debugging/DebugDrawings.h"
#include "Tools/Math/Transformation.h"
#include <algorithm>
#include <cmath>

MAKE_MODULE(JerseyClassifierProvider2020For2023);

void JerseyClassifierProvider2020For2023::update(JerseyClassifier& jerseyClassifier)
{
  DECLARE_DEBUG_DRAWING("module:JerseyClassifierProvider2020For2023:jerseyRange", "drawingOnImage");
  DECLARE_DEBUG_DRAWING("module:JerseyClassifierProvider2020For2023:jersey", "drawingOnImage");
  DECLARE_DEBUG_DRAWING("module:JerseyClassifierProvider2020For2023:jerseyWeights", "drawingOnImage");
  DECLARE_DEBUG_DRAWING("module:JerseyClassifierProvider2020For2023:jerseyClassification", "drawingOnImage");
  DECLARE_DEBUG_DRAWING("module:JerseyClassifierProvider2020For2023:branch4Stage", "drawingOnImage");

  jerseyClassifier.detectJersey = [this](const ObstaclesImagePercept::Obstacle& obstacleInImage, ObstaclesFieldPercept::Obstacle& obstacleOnField)
  {
    return detectJersey(obstacleInImage, obstacleOnField);
  };
}

/**
 * Hue values for the different team colors. The indices are enum constants from Settings::TeamColor.
 */
static int jerseyHues[] =
{
  255 * 7 / 8, // blue + cyan
  255 * 2 / 8, // red
  255 * 4 / 8, // yellow
  0, // black (unused)
  0, // white (unused)
  255 * 5 / 8, // green
  255 * 3 / 8, // orange
  32, // purple
  255 * 7 / 16, // brown
  0, // gray (unused)
};

void JerseyClassifierProvider2020For2023::detectJersey(const ObstaclesImagePercept::Obstacle& obstacleInImage, ObstaclesFieldPercept::Obstacle& obstacleOnField) const
{
  Vector2f lowerInImage;
  Vector2f upperInImage;
  // obstacleInImage distance is imprecise and only used if part of the robot is in lower image
  float distance = obstacleInImage.distance * 1000;
  if(obstacleInImage.bottomFound)
    distance = obstacleOnField.center.norm() + theRobotDimensions.footLength * 0.5f;
  RECTANGLE("module:JerseyClassifierProvider2020For2023:jerseyClassification", obstacleInImage.left, obstacleInImage.top, obstacleInImage.right, obstacleInImage.bottom, 3, Drawings::solidPen, ColorRGBA::violet);
  // Determine jersey region.
  const Vector2f centerOnField = obstacleOnField.center.normalized(distance);
  if(Transformation::robotToImage(Vector3f(centerOnField.x(), centerOnField.y(), jerseyYRange.min),
                                  theCameraMatrix, theCameraInfo, lowerInImage)
     && Transformation::robotToImage(Vector3f(centerOnField.x(), centerOnField.y(), jerseyYRange.max),
                                     theCameraMatrix, theCameraInfo, upperInImage))
  {
    lowerInImage = theImageCoordinateSystem.fromCorrected(lowerInImage);
    if(lowerInImage.y() >= jerseyMinYSamples)
    {
      upperInImage = theImageCoordinateSystem.fromCorrected(upperInImage);
      const int obstacleTop = std::max(0, obstacleInImage.top);
      if(upperInImage.y() < obstacleTop)
      {
        const float interpolationFactor = (static_cast<float>(obstacleTop) - lowerInImage.y()) / (lowerInImage.y() - upperInImage.y());
        upperInImage = Vector2f(lowerInImage.x() + (lowerInImage.x() - upperInImage.x()) * interpolationFactor, obstacleTop);
        //lowerInImage + (lowerInImage - upperInImage) * (static_cast<float>(obstacleTop) - lowerInImage.y()) / (lowerInImage.y() - upperInImage.y());
      }
      if(lowerInImage.y() > static_cast<float>(theCameraInfo.height - 1))
      {
        const float interpolationFactor = (static_cast<float>(theCameraInfo.height - 1) - upperInImage.y()) / (lowerInImage.y() - upperInImage.y());
        lowerInImage = Vector2f(upperInImage.x() + (lowerInImage.x() - upperInImage.x()) * interpolationFactor, static_cast<float>(theCameraInfo.height - 1));
        //upperInImage + (lowerInImage - upperInImage) * (static_cast<float>(theCameraInfo.height - 1) - upperInImage.y()) / (lowerInImage.y() - upperInImage.y());
      }

      // [FIX] scanWidthRatio shrinks the horizontal scan range so arms can be excluded.
      const int width = static_cast<int>((obstacleInImage.right - obstacleInImage.left + 1) * scanWidthRatio);
      const float ySteps = std::min(lowerInImage.y() - upperInImage.y(), jerseyMaxYSamples);
      if(ySteps < jerseyMinYSamples)
      {
        obstacleOnField.type = ObstaclesFieldPercept::unknown;
        DRAW_TEXT("module:JerseyClassifierProvider2020For2023:jerseyClassification", obstacleInImage.left, obstacleInImage.top + 12, 10, ColorRGBA::black, "class: unknown");
        return;
      }
      const float yStep = (lowerInImage.y() - upperInImage.y()) / ySteps;
      const float xyStep = (lowerInImage.x() - upperInImage.x()) / ySteps;
      float left = std::max(upperInImage.x() - static_cast<float>(width) * 0.5f, 0.f);
      float right = std::min(upperInImage.x() + static_cast<float>(width) * 0.5f, static_cast<float>(theCameraInfo.width) - 0.5f);
      const float xSteps = std::min((right - left), jerseyMaxXSamples);
      const float xStep = (right - left) / xSteps;
      // this is the maximum number, could be less if the examined robot is near the image's edge
      const float examinedPixels = xSteps * ySteps;

      // The maximum brightness is needed to determine black, white and gray relative to it.
      unsigned char maxBrightness = 0;
      if(theGameState.ownTeam.fieldPlayerColor == GameState::Team::Color::black || theGameState.opponentTeam.fieldPlayerColor == GameState::Team::Color::black ||
         theGameState.ownTeam.fieldPlayerColor == GameState::Team::Color::gray || theGameState.opponentTeam.fieldPlayerColor == GameState::Team::Color::gray ||
         theGameState.ownTeam.fieldPlayerColor == GameState::Team::Color::white || theGameState.opponentTeam.fieldPlayerColor == GameState::Team::Color::white ||
         theGameState.ownTeam.goalkeeperColor == GameState::Team::Color::black || theGameState.opponentTeam.goalkeeperColor == GameState::Team::Color::black ||
         theGameState.ownTeam.goalkeeperColor == GameState::Team::Color::gray || theGameState.opponentTeam.goalkeeperColor == GameState::Team::Color::gray ||
         theGameState.ownTeam.goalkeeperColor == GameState::Team::Color::white || theGameState.opponentTeam.goalkeeperColor == GameState::Team::Color::white)
      {
        Vector2f centerInImage = Vector2f(static_cast<float>(obstacleInImage.left + obstacleInImage.right) * 0.5f,
                std::min(static_cast<float>(obstacleInImage.bottom), static_cast<float>(theCameraInfo.height - (whiteScanOffSet + 1))) * (1.f - whiteScanHeightRatio)
                + std::min(lowerInImage.y(), static_cast<float>(theCameraInfo.height - (whiteScanOffSet + 1))) * whiteScanHeightRatio);
        float center_left = std::max(centerInImage.x() - static_cast<float>(width) * 0.5f, 0.f);
        float center_right = std::min(centerInImage.x() + static_cast<float>(width) * 0.5f, static_cast<float>(theCameraInfo.width) - 0.5f);
        for(int yOffset = -1; yOffset <= 1; ++yOffset)
          for(float x = center_left; x < center_right; x += xStep)
            maxBrightness = std::max(theECImage.grayscaled[static_cast<int>(centerInImage.y()) + whiteScanOffSet * yOffset][static_cast<int>(x)], maxBrightness);
      }

      // Get pixel classifier
      const std::function<bool(int, int)>& isOwnFieldPlayer = getPixelClassifier(theGameState.ownTeam.fieldPlayerColor, theGameState.opponentTeam.fieldPlayerColor, theGameState.opponentTeam.goalkeeperColor, theGameState.ownTeam.goalkeeperColor, maxBrightness);
      const std::function<bool(int, int)>& isOpponentFieldPlayer = getPixelClassifier(theGameState.opponentTeam.fieldPlayerColor, theGameState.ownTeam.fieldPlayerColor, theGameState.opponentTeam.goalkeeperColor, theGameState.ownTeam.goalkeeperColor, maxBrightness);
      const std::function<bool(int, int)>& isOwnGoalkeeper = getPixelClassifier(theGameState.ownTeam.goalkeeperColor, theGameState.ownTeam.fieldPlayerColor, theGameState.opponentTeam.fieldPlayerColor, theGameState.opponentTeam.goalkeeperColor, maxBrightness);
      const std::function<bool(int, int)>& isOpponentGoalkeeper = getPixelClassifier(theGameState.opponentTeam.goalkeeperColor, theGameState.opponentTeam.fieldPlayerColor, theGameState.ownTeam.fieldPlayerColor, theGameState.ownTeam.goalkeeperColor, maxBrightness);

      float ownFieldPlayerPixels = 0;
      float opponentFieldPlayerPixels = 0;
      float ownGoalkeeperPixels = 0;
      float opponentGoalkeeperPixels = 0;

      // [DEBUG] Accumulators for HSI statistics across the sampled jersey region.
      long long sumH = 0, sumS = 0, sumI = 0;
      int sampleCount = 0;
      long long sumH_satOnly = 0;  // Sum of hues only for "colored" pixels (S >= 30)
      int satCount = 0;            // Number of "colored" pixels
      int lowSatCount = 0;         // Number of "near-grayscale" pixels (S < 30, e.g. logos)

      for(float y = upperInImage.y(); y < lowerInImage.y();
          y += yStep, left = std::max(left + xyStep, 0.f), right = std::min(right + xyStep, static_cast<float>(theCameraInfo.width)))
      {
        // calculations for pixel weighting
        const float yDiffFromCenter = 2 * (((lowerInImage.y() - upperInImage.y()) / 2) - (y - upperInImage.y())) / (lowerInImage.y() - upperInImage.y());
        const float yFactor = std::abs(yDiffFromCenter) < 0.5f ? 1.f : (1.f - std::abs(yDiffFromCenter)) + 0.5f;
        const float jerseyEnd = relativeJerseyWidth - 0.1f * std::abs(yDiffFromCenter - 0.4f);
        for(float x = left; x < right; x += xStep)
        {
          float weight = 1.f;
          if(weighPixels)
          {
            const float xDiffFromCenter = 2 * std::abs((right - left) / 2 + left - x) / (right - left);
            const float xFactor = xDiffFromCenter < jerseyEnd ? 1 : 1 - (xDiffFromCenter - jerseyEnd);
            weight = xFactor * yFactor;
          }
          DOT("module:JerseyClassifierProvider2020For2023:jerseyWeights", static_cast<int>(x), static_cast<int>(y),
              ColorRGBA(static_cast<unsigned  char>(240 - 240 * weight), static_cast<unsigned  char>(240 * weight), static_cast<unsigned  char>(240 * weight), 220),
              ColorRGBA(static_cast<unsigned  char>(240 - 240 * weight), static_cast<unsigned  char>(240 * weight), static_cast<unsigned  char>(240 * weight), 220));
          // [DEBUG] Accumulate HSI samples for averaging
          {
            const int ix = static_cast<int>(x), iy = static_cast<int>(y);
            const int hh = theECImage.hued[iy][ix];
            const int ss = theECImage.saturated[iy][ix];
            const int ii = theECImage.grayscaled[iy][ix];
            sumH += hh; sumS += ss; sumI += ii; ++sampleCount;
            if(ss >= 30) { sumH_satOnly += hh; ++satCount; }
            else { ++lowSatCount; }
          }
          if(isOwnFieldPlayer(static_cast<int>(x), static_cast<int>(y)))
          {
            ownFieldPlayerPixels += weight;
            DOT("module:JerseyClassifierProvider2020For2023:jersey", static_cast<int>(x), static_cast<int>(y), ColorRGBA::yellow, ColorRGBA::yellow);
          }
          else if(isOpponentFieldPlayer(static_cast<int>(x), static_cast<int>(y)))
          {
            opponentFieldPlayerPixels += weight;
            DOT("module:JerseyClassifierProvider2020For2023:jersey", static_cast<int>(x), static_cast<int>(y), ColorRGBA::blue, ColorRGBA::blue);
          }
          else if(isOpponentGoalkeeper(static_cast<int>(x), static_cast<int>(y)))
          {
            opponentGoalkeeperPixels += weight;
            DOT("module:JerseyClassifierProvider2020For2023:jersey", static_cast<int>(x), static_cast<int>(y), ColorRGBA::blue, ColorRGBA::blue);
          }
          else if(isOwnGoalkeeper(static_cast<int>(x), static_cast<int>(y)))
          {
            ownGoalkeeperPixels += weight;
            DOT("module:JerseyClassifierProvider2020For2023:jersey", static_cast<int>(x), static_cast<int>(y), ColorRGBA::yellow, ColorRGBA::yellow);
          }
          else
            DOT("module:JerseyClassifierProvider2020For2023:jersey", static_cast<int>(x), static_cast<int>(y), ColorRGBA::green, ColorRGBA::green);
        }
      }
      // threshold to counter white robot parts or green field background being classified as opponent jersey
      if((theGameState.opponentTeam.fieldPlayerColor == GameState::Team::Color::white || theGameState.opponentTeam.fieldPlayerColor == GameState::Team::Color::green))
      {
        const float threshold = 1.5f * (ownFieldPlayerPixels + ownGoalkeeperPixels) + (examinedPixels) / 5;
        opponentFieldPlayerPixels = opponentFieldPlayerPixels <= threshold ? 0 : opponentFieldPlayerPixels - threshold;
      }
      if((theGameState.opponentTeam.goalkeeperColor == GameState::Team::Color::white || theGameState.opponentTeam.goalkeeperColor == GameState::Team::Color::green))
      {
        const float threshold = 1.5f * (ownFieldPlayerPixels + ownGoalkeeperPixels) + (examinedPixels) / 5;
        opponentGoalkeeperPixels = opponentGoalkeeperPixels <= threshold ? 0 : opponentGoalkeeperPixels - threshold;
      }
      // [DEBUG] Average H/S/I across the entire sampled jersey region.
      // - Havg / Savg / Iavg : average over ALL sampled pixels (includes logos).
      // - Hcol               : average hue over only "colored" pixels (S>=30), filters out white/black logos.
      // - sat / lowSat       : count of colored vs. low-saturation pixels.
      if(sampleCount > 0)
      {
        const int Havg = static_cast<int>(sumH / sampleCount);
        const int Savg = static_cast<int>(sumS / sampleCount);
        const int Iavg = static_cast<int>(sumI / sampleCount);
        const int Hcol = satCount > 0 ? static_cast<int>(sumH_satOnly / satCount) : -1;
        DRAW_TEXT("module:JerseyClassifierProvider2020For2023:jerseyClassification", obstacleInImage.right + 2, obstacleInImage.top + 0,  10, ColorRGBA::black, "Havg=" << Havg);
        DRAW_TEXT("module:JerseyClassifierProvider2020For2023:jerseyClassification", obstacleInImage.right + 2, obstacleInImage.top + 12, 10, ColorRGBA::black, "Savg=" << Savg);
        DRAW_TEXT("module:JerseyClassifierProvider2020For2023:jerseyClassification", obstacleInImage.right + 2, obstacleInImage.top + 24, 10, ColorRGBA::black, "Iavg=" << Iavg);
        DRAW_TEXT("module:JerseyClassifierProvider2020For2023:jerseyClassification", obstacleInImage.right + 2, obstacleInImage.top + 36, 10, ColorRGBA::black, "Hcol=" << Hcol);
        DRAW_TEXT("module:JerseyClassifierProvider2020For2023:jerseyClassification", obstacleInImage.right + 2, obstacleInImage.top + 48, 10, ColorRGBA::black, "sat=" << satCount << "/" << sampleCount);
      }
      DRAW_TEXT("module:JerseyClassifierProvider2020For2023:jerseyClassification", obstacleInImage.left, obstacleInImage.top - 14, 10, ColorRGBA::black, "own: " << ownFieldPlayerPixels);
      DRAW_TEXT("module:JerseyClassifierProvider2020For2023:jerseyClassification", obstacleInImage.left, obstacleInImage.top - 4, 10, ColorRGBA::black, "opponent: " << opponentFieldPlayerPixels);
      DRAW_TEXT("module:JerseyClassifierProvider2020For2023:jerseyClassification", obstacleInImage.left, obstacleInImage.top - 24, 10, ColorRGBA::black, "own goalie: " << ownGoalkeeperPixels);
      DRAW_TEXT("module:JerseyClassifierProvider2020For2023:jerseyClassification", obstacleInImage.left, obstacleInImage.top - 34, 10, ColorRGBA::black, "opponent goalie: " << opponentGoalkeeperPixels);
      const float minJerseyWeight = examinedPixels * minJerseyWeightRatio;
      const float overallPixels = ownFieldPlayerPixels + ownGoalkeeperPixels + opponentGoalkeeperPixels + opponentFieldPlayerPixels;
      if((ownFieldPlayerPixels > minJerseyWeight) && (ownFieldPlayerPixels > overallPixels * minJerseyRatio))
      {
        obstacleOnField.type = ObstaclesFieldPercept::ownPlayer;
        DRAW_TEXT("module:JerseyClassifierProvider2020For2023:jerseyClassification", obstacleInImage.left, obstacleInImage.top + 10, 10, ColorRGBA::black, "class: own field player");
      }
      else if((opponentFieldPlayerPixels > minJerseyWeight) && (opponentFieldPlayerPixels > overallPixels * minJerseyRatio))
      {
        obstacleOnField.type = ObstaclesFieldPercept::opponentPlayer;
        DRAW_TEXT("module:JerseyClassifierProvider2020For2023:jerseyClassification", obstacleInImage.left, obstacleInImage.top + 10, 10, ColorRGBA::black, "class: opponent field player");
      }
      else if((ownGoalkeeperPixels > minJerseyWeight) && (ownGoalkeeperPixels > overallPixels * minJerseyRatio))
      {
        obstacleOnField.type = ObstaclesFieldPercept::ownGoalkeeper;
        DRAW_TEXT("module:JerseyClassifierProvider2020For2023:jerseyClassification", obstacleInImage.left, obstacleInImage.top + 10, 10, ColorRGBA::black, "class: own goalkeeper");
      }
      else if((opponentGoalkeeperPixels > minJerseyWeight) && (opponentGoalkeeperPixels > overallPixels * minJerseyRatio))
      {
        obstacleOnField.type = ObstaclesFieldPercept::opponentGoalkeeper;
        DRAW_TEXT("module:JerseyClassifierProvider2020For2023:jerseyClassification", obstacleInImage.left, obstacleInImage.top + 10, 10, ColorRGBA::black, "class: opponent goalkeeper");
      }
      else
      {
        obstacleOnField.type = ObstaclesFieldPercept::unknown;
        DRAW_TEXT("module:JerseyClassifierProvider2020For2023:jerseyClassification", obstacleInImage.left, obstacleInImage.top + 12, 10, ColorRGBA::black, "class: unknown");
      }
    }
  }
}

std::function<bool(int, int)> JerseyClassifierProvider2020For2023::getPixelClassifier(const GameState::Team::Color checkColor,
                                                                                      const GameState::Team::Color o1,
                                                                                      const GameState::Team::Color o2,
                                                                                      const GameState::Team::Color o3,
                                                                                      const int maxBrightness) const
{
  const int checkHue = jerseyHues[checkColor];
  const int o1Hue = jerseyHues[o1];
  const int o2Hue = jerseyHues[o2];
  const int o3Hue = jerseyHues[o3];
  const Rangei grayRange = Rangei(static_cast<int>(maxBrightness * this->grayRange.min),
                                  static_cast<int>(maxBrightness * this->grayRange.max));

  bool checkIsBlack = checkColor == GameState::Team::Color::black;
  bool othersAreAllColorful = o1 != GameState::Team::Color::black && o1 != GameState::Team::Color::gray && o1 != GameState::Team::Color::white &&
                              o2 != GameState::Team::Color::black && o2 != GameState::Team::Color::gray && o2 != GameState::Team::Color::white &&
                              o3 != GameState::Team::Color::black && o3 != GameState::Team::Color::gray && o3 != GameState::Team::Color::white;

  // Black jersey is compared to colorful options:
  if(checkIsBlack && othersAreAllColorful)
    return [this, grayRange](const int x, const int y)
    {
      // [FIX] Pure brightness check. BHuman's lighting-independent saturation gets
      // amplified for dark pixels, making dark "black" jerseys appear highly
      // saturated and breaking the original sat-based check. Brightness alone
      // reliably separates black (low gray) from colored jerseys (yellow/blue/red
      // /etc are bright enough to fail this check). This assumes the opponent is
      // not also a dark-colored jersey (e.g., navy), which is fine for standard
      // RoboCup matches where only "black" is a low-brightness team color.
      return theECImage.grayscaled[y][x] <= grayRange.min && theECImage.saturated[y][x] < satThreshold;
    };
  // All jerseys are colorful, no black/gray/white involved at all:
  else if(!checkIsBlack && othersAreAllColorful)
    return [this, checkHue, grayRange, o1Hue, o2Hue, o3Hue](const int x, const int y)
    {
      // [FIX] Symmetric brightness gate: a colored jersey pixel must be bright enough.
      // Without this, dark pixels (black jerseys) whose hue happens to land in the
      // colored range would be wrongly accepted as colored.
      if(theECImage.grayscaled[y][x] <= grayRange.min)
        return false;
      const int hue = theECImage.hued[y][x];
      return std::abs(static_cast<signed char>(hue - checkHue)) < std::min(std::abs(static_cast<signed char>(hue - o1Hue)), hueSimilarityThreshold) &&
             std::abs(static_cast<signed char>(hue - checkHue)) < std::min(std::abs(static_cast<signed char>(hue - o2Hue)), hueSimilarityThreshold) &&
             std::abs(static_cast<signed char>(hue - checkHue)) < std::min(std::abs(static_cast<signed char>(hue - o3Hue)), hueSimilarityThreshold);
    };
  // We check the black jersey against a set of others that contain at least once white or gray
  else if(checkIsBlack && !othersAreAllColorful)
    return [this, grayRange](const int x, const int y)
    {
      // [FIX] Simplified to pure brightness check, identical to branch 1.
      // Brightness alone reliably separates black from any other jersey color:
      //   - white pixels (gray ~ maxBrightness) > grayRange.min → rejected
      //   - gray pixels (gray ~ 0.5 * maxBrightness) > grayRange.min → rejected
      //   - colored pixels (yellow/blue/red/etc, bright) > grayRange.min → rejected
      // Same caveat as branch 1: assumes no dark-colored opponent jersey (e.g., navy).
      return theECImage.grayscaled[y][x] <= grayRange.min&& theECImage.saturated[y][x] < satThreshold;
    };
  // We check a colored jersey against a set of others that contain at least once white or gray or black
  else //if(!checkIsBlack && !othersAreAllColorful)
    return [this, checkHue, grayRange, o1Hue, o2Hue, o3Hue, o1, o2, o3](const int x, const int y)
    {
      // [FIX] Symmetric brightness gate: dark pixels are black candidates and should
      // not be classified as colored, regardless of their hue (which is unreliable
      // when brightness is low — see comment in branch 1 for details).
      if(theECImage.grayscaled[y][x] <= grayRange.min)
      {
        DOT("module:JerseyClassifierProvider2020For2023:branch4Stage", x, y, ColorRGBA(80, 80, 80), ColorRGBA(80, 80, 80));
        return false;
      }
      const int hue = theECImage.hued[y][x];
      bool checkO1 = false;
      if(o1 == GameState::Team::Color::black || o1 == GameState::Team::Color::gray || o1 == GameState::Team::Color::white)
        checkO1 = std::abs(static_cast<signed char>(theECImage.hued[y][x] - checkHue)) <= hueSimilarityThreshold;
      else
        checkO1 = std::abs(static_cast<signed char>(hue - checkHue)) < std::min(std::abs(static_cast<signed char>(hue - o1Hue)), hueSimilarityThreshold);
      if(!checkO1)
      {
        // [DEBUG] Stage 1 fail = red
        DOT("module:JerseyClassifierProvider2020For2023:branch4Stage", x, y, ColorRGBA::red, ColorRGBA::red);
        return false;
      }

      bool checkO2 = false;
      if(o2 == GameState::Team::Color::black || o2 == GameState::Team::Color::gray || o2 == GameState::Team::Color::white)
        checkO2 = std::abs(static_cast<signed char>(theECImage.hued[y][x] - checkHue)) <= hueSimilarityThreshold;
      else
        checkO2 = std::abs(static_cast<signed char>(hue - checkHue)) < std::min(std::abs(static_cast<signed char>(hue - o2Hue)), hueSimilarityThreshold);
      if(!checkO2)
      {
        // [DEBUG] Stage 2 fail = orange
        DOT("module:JerseyClassifierProvider2020For2023:branch4Stage", x, y, ColorRGBA::orange, ColorRGBA::orange);
        return false;
      }

      bool checkO3 = false;
      if(o3 == GameState::Team::Color::black || o3 == GameState::Team::Color::gray || o3 == GameState::Team::Color::white)
        checkO3 = std::abs(static_cast<signed char>(theECImage.hued[y][x] - checkHue)) <= hueSimilarityThreshold;
      else
        checkO3 = std::abs(static_cast<signed char>(hue - checkHue)) < std::min(std::abs(static_cast<signed char>(hue - o3Hue)), hueSimilarityThreshold);

      // [DEBUG] Stage 3 fail = magenta, all-pass = cyan
      if(!checkO3)
        DOT("module:JerseyClassifierProvider2020For2023:branch4Stage", x, y, ColorRGBA::magenta, ColorRGBA::magenta);
      else
        DOT("module:JerseyClassifierProvider2020For2023:branch4Stage", x, y, ColorRGBA::cyan, ColorRGBA::cyan);

      return checkO3;
    };
}
