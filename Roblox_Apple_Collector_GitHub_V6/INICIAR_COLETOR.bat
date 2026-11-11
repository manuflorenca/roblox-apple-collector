@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1
where py >nul 2>&1
if errorlevel 1 (
  echo Python nao foi encontrado. Instale o Python no Windows.
  pause
  exit /b 1
)
py -c "import cv2, numpy, mss, pydirectinput, keyboard, win32gui" >nul 2>&1
if errorlevel 1 (
  echo Instalando bibliotecas necessarias...
  py -m pip install -r requirements.txt
  if errorlevel 1 (
    echo FALHA na instalacao. Veja as mensagens acima.
    pause
    exit /b 1
  )
)
echo.
echo ================================================================
echo        COLETOR DE MACAS V6 - RAPIDO + AUTO RECUPERACAO
echo ================================================================
echo  5 + ENTER = marcar a cerca e o SEU avatar
 echo  7 + ENTER = iniciar, depois clicar no Roblox
 echo  8 + ENTER = PARAR no CMD (ou F8 em qualquer janela)
echo  1/2/3 + ENTER = velocidade normal / RAPIDA / TURBO
echo  F9 ou 9 + ENTER = pausar ou retomar manualmente
 echo  0 + ENTER = sair
 echo  A perda de rastreamento agora tenta se corrigir sozinha.
echo ================================================================
echo.
py coletor_macas_roblox.py
if errorlevel 1 echo O programa terminou com erro; copie o erro para analisarmos.
pause
