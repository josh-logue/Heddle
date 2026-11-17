; Heddle in .json's "Open with" list, without becoming the default for .json files
; (decided 2026-11-16), for this user only. Run by the one-click installer (electron-builder).

!macro customInstall
  WriteRegStr HKCU "Software\Classes\Heddle.board" "" "Heddle board"
  WriteRegStr HKCU "Software\Classes\Heddle.board\DefaultIcon" "" "$INSTDIR\Heddle.exe,0"
  WriteRegStr HKCU "Software\Classes\Heddle.board\shell\open\command" "" '"$INSTDIR\Heddle.exe" "%1"'
  WriteRegStr HKCU "Software\Classes\.json\OpenWithProgids" "Heddle.board" ""
  WriteRegStr HKCU "Software\Classes\Applications\Heddle.exe" "FriendlyAppName" "Heddle"
  WriteRegStr HKCU "Software\Classes\Applications\Heddle.exe\SupportedTypes" ".json" ""
  WriteRegStr HKCU "Software\Classes\Applications\Heddle.exe\shell\open\command" "" '"$INSTDIR\Heddle.exe" "%1"'
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
!macroend

!macro customUnInstall
  DeleteRegValue HKCU "Software\Classes\.json\OpenWithProgids" "Heddle.board"
  DeleteRegKey HKCU "Software\Classes\Heddle.board"
  DeleteRegKey HKCU "Software\Classes\Applications\Heddle.exe"
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
!macroend
