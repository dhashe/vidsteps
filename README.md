# vidsteps

A minimal tool for dividing a video into a series of steps, and then playing the video step by step, looping the current step until told to advance.

Step timings are saved to a local database and read on subsequent runs.

vidsteps was developed to make it easier for me to follow along with recipe videos as I cook. Its primary purpose is to be useful for me for that purpose, but you may find it useful as well.

## Installing

vidsteps has been tested on Linux, MacOS, and Windows. On all platforms, ffmpeg must be installed through a native package manager. pip will take care of the rest.

## Help text

```
usage: vidsteps [-h] [-r] video_file

Play a video one step at a time.

positional arguments:
  video_file    Video file to use.

options:
  -h, --help    show this help message and exit
  -r, --record  Re-record the step timestamps and overwrite any that already exists.
```

## Keybindings

Recording mode: (p) Pause, (space / return) Add step, (ctrl-c / q) Quit.

Playing mode: (p) Pause, (space / return / j / l / right arrow) Next step, (h / k / left arrow) Prev step, (0 / backspace) Restart current step, (ctrl-c / q) Quit.
