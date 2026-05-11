/**
 * @file SimulatedNao/CommandServer.h
 *
 * This file declares a TCP command server for external GUI control.
 */

#pragma once

#include <string>
#include <thread>
#include <mutex>
#include <vector>
#include <atomic>

#ifdef WINDOWS
#include <WinSock2.h>
#include <ws2tcpip.h>
#pragma comment(lib, "ws2_32.lib")
#else
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>
#endif

/**
 * The class implements a TCP command server that listens on a port
 * and accepts commands from external GUI applications.
 */
class CommandServer
{
public:
  /**
   * Constructor.
   * @param port The TCP port to listen on.
   */
  CommandServer(int port = 12345);

  /** Destructor. */
  ~CommandServer();

  /**
   * Starts the server.
   */
  void start();

  /**
   * Stops the server.
   */
  void stop();

  /**
   * Gets the pending commands received from external clients.
   * @return A list of command strings.
   */
  std::vector<std::string> getPendingCommands();

private:
  /**
   * The main server loop that accepts connections and reads commands.
   */
  void serverLoop();

  int port; /**< The TCP port to listen on. */
  std::atomic<bool> running; /**< Whether the server is running. */
  std::thread serverThread; /**< The server thread. */
  std::mutex commandMutex; /**< Mutex for the command queue. */
  std::vector<std::string> pendingCommands; /**< Commands received from clients. */

#ifdef WINDOWS
  SOCKET serverSocket; /**< The server socket. */
#else
  int serverSocket; /**< The server socket. */
#endif
};
