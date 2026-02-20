Current version: CarbonfX12g_v5.py //scenarios and stereo phantom

Final (audio /accustic) version: CarbonXI.py


<img width="964" alt="carboNmp" src="https://github.com/stpf99/carbONmp/blob/dcb9d1a8956acaa6638dd66eea1b66e50609365d/CarbonXI.png">

Auto-loaded 178 channels from channels.m3u

qt.multimedia.ffmpeg: Using Qt multimedia with FFmpeg version 7.1.2 LGPL version 2.1 or later

✓ Virtual sink 'carbon_monitor' already exists

✓ Main playbin stopped

🎤 Creating fresh monitoring pipeline for: carbon_monitor.monitor

✓ All elements linked successfully

✓ Pipeline chain created:

  monitor_src -> audioconvert -> audioresample -> tape_sat ->
  
  tape_gain -> tape_tone -> EQ -> spatial_sat -> conv1 ->
  
  stereo -> conv2 -> spatial_echo -> conv3 ->
  
  spectrum -> audioconvert2 -> audio_sink

✓ Pipeline set to READY state

✓ Monitoring pipeline with full FX chain created successfully

✓ Tape Saturation widget connected to GStreamer elements

✓ Tape Saturation widget found monitoring pipeline elements

🎛️ Applying initial Tape values...

🎛️ Tape Drive: 50 → threshold=0.50, gain=1.40x

