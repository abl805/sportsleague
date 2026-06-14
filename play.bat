@echo off
:menu
cls
echo.
echo  ============================================
echo   BASKETBALL LEAGUE SIMULATOR
echo  ============================================
echo.
echo   1.  New Season       (wipe and re-seed)
echo   2.  Simulate Week
echo   3.  Simulate Week    (with drama narration)
echo   4.  Review Trades
echo   5.  Standings
echo   6.  Drama Report
echo   7.  Web App
echo   8.  Legacy Streamlit Dashboard
echo   9.  Exit
echo.
set /p choice=  Choose (1-9):

if "%choice%"=="1" goto new_season
if "%choice%"=="2" goto week
if "%choice%"=="3" goto week_verbose
if "%choice%"=="4" goto trades
if "%choice%"=="5" goto standings
if "%choice%"=="6" goto drama
if "%choice%"=="7" goto webapp
if "%choice%"=="8" goto streamlit
if "%choice%"=="9" exit /b

echo   Not a valid choice. Try again.
pause > nul
goto menu

:new_season
python seed.py
goto done

:week
python run_week.py
goto done

:week_verbose
python run_week.py --verbose
goto done

:trades
python review_trades.py
goto done

:standings
python view_league.py
goto done

:drama
python view_drama.py
goto done

:webapp
python web_app.py
goto done

:streamlit
streamlit run app.py
goto done

:done
echo.
echo  Press any key to return to the menu...
pause > nul
goto menu
