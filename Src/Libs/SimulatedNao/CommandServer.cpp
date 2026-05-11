/**
 * @file SimulatedNao/CommandServer.cpp
 *
 * This file implements a TCP command server for external GUI control.
 */

#include "CommandServer.h"
#include "Platform/BHAssert.h"
#include <cstring>
#include <algorithm>

#ifdef WINDOWS
#else
#include <fcntl.h>
#include <errno.h>
#endif

CommandServer::CommandServer(int port) : port(port), running(false)
#ifdef WINDOWS
  , serverSocket(INVALID_SOCKET)
#else
  , serverSocket(-1)
#endif
{
}

CommandServer::~CommandServer()
{
  stop();
}

void CommandServer::start()
{
  if(running)
    return;

#ifdef WINDOWS
  WSADATA wsaData;
  WSAStartup(MAKEWORD(2, 2), &wsaData);
  serverSocket = socket(AF_INET, SOCK_STREAM, 0);
  ASSERT(serverSocket != INVALID_SOCKET);
#else
  serverSocket = socket(AF_INET, SOCK_STREAM, 0);
  ASSERT(serverSocket >= 0);
  // Allow address reuse
  int opt = 1;
  setsockopt(serverSocket, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
#endif

  struct sockaddr_in serverAddr;
  memset(&serverAddr, 0, sizeof(serverAddr));
  serverAddr.sin_family = AF_INET;
  serverAddr.sin_addr.s_addr = INADDR_ANY;
  serverAddr.sin_port = htons(static_cast<uint16_t>(port));

  if(bind(serverSocket, reinterpret_cast<struct sockaddr*>(&serverAddr), sizeof(serverAddr)) < 0)
  {
#ifdef WINDOWS
    closesocket(serverSocket);
    WSACleanup();
#else
    close(serverSocket);
#endif
    return;
  }

  listen(serverSocket, 5);

  running = true;
  serverThread = std::thread(&CommandServer::serverLoop, this);
}

void CommandServer::stop()
{
  if(!running)
    return;

  running = false;

#ifdef WINDOWS
  closesocket(serverSocket);
  WSACleanup();
#else
  shutdown(serverSocket, SHUT_RDWR);
  close(serverSocket);
#endif

  if(serverThread.joinable())
    serverThread.join();
}

std::vector<std::string> CommandServer::getPendingCommands()
{
  std::lock_guard<std::mutex> lock(commandMutex);
  std::vector<std::string> commands = std::move(pendingCommands);
  pendingCommands.clear();
  return commands;
}

void CommandServer::serverLoop()
{
  while(running)
  {
    struct sockaddr_in clientAddr;
    socklen_t clientLen = sizeof(clientAddr);

#ifdef WINDOWS
    SOCKET clientSocket = accept(serverSocket, reinterpret_cast<struct sockaddr*>(&clientAddr), &clientLen);
    if(clientSocket == INVALID_SOCKET)
      continue;
#else
    int clientSocket = accept(serverSocket, reinterpret_cast<struct sockaddr*>(&clientAddr), &clientLen);
    if(clientSocket < 0)
      continue;
#endif

    // Set a timeout so we don't block forever
    struct timeval tv;
    tv.tv_sec = 1;
    tv.tv_usec = 0;
    setsockopt(clientSocket, SOL_SOCKET, SO_RCVTIMEO, reinterpret_cast<const char*>(&tv), sizeof(tv));

    // Read commands from the client until it disconnects
    char buffer[1024];
    std::string commandBuffer;
    while(running)
    {
      ssize_t bytesRead = recv(clientSocket, buffer, sizeof(buffer) - 1, 0);
      if(bytesRead <= 0)
        break;

      buffer[bytesRead] = '\0';
      commandBuffer += buffer;

      // Process complete lines (commands end with newline)
      size_t pos;
      while((pos = commandBuffer.find('\n')) != std::string::npos)
      {
        std::string command = commandBuffer.substr(0, pos);
        commandBuffer.erase(0, pos + 1);

        // Trim whitespace
        while(!command.empty() && (command.back() == '\r' || command.back() == ' '))
          command.pop_back();
        while(!command.empty() && (command.front() == ' ' || command.front() == '\t'))
          command.erase(command.begin());

        if(!command.empty())
        {
          std::lock_guard<std::mutex> lock(commandMutex);
          pendingCommands.push_back(command);
        }
      }
    }

#ifdef WINDOWS
    closesocket(clientSocket);
#else
    close(clientSocket);
#endif
  }
}
