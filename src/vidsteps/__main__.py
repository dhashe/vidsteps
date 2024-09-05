#!/usr/bin/env python3

import argparse
import itertools
import json
import os.path
import sqlite3
import tempfile

import appdirs
import moviepy.editor
import pygame

#
# Database access layer
#

def set_timestamps_for_video(cursor, video_path: str, timestamps: list[int]):
    """Insert a timestamp into the database."""
    cursor.execute('''
        INSERT INTO video_timestamps (path, timestamps) VALUES (?, ?)
        ON CONFLICT (path) DO UPDATE SET timestamps = excluded.timestamps
    ''', (video_path, json.dumps(timestamps).encode("utf8")))


def get_timestamps_for_video(cursor, video_path: str) -> list[int]:
    """Return the list of all timestamps for the video."""
    try:
        return json.loads(next(cursor.execute('''
            SELECT timestamps FROM video_timestamps WHERE path = ?
        ''', (video_path,)))[0].decode("utf8"))
    except StopIteration:
        return []


def init_database(cursor):
    """Initialize the database."""
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS video_timestamps (
        path TEXT PRIMARY KEY,
        timestamps BLOB NOT NULL
    )
    ''')

#
# UI helpers
#


def resize_keep_aspect_ratio(original_width, original_height, new_height):
    """Resize the (original_width, original_height) pair to have height new_height and width that maintains the same aspect ratio."""
    aspect_ratio = original_width / original_height
    new_width = new_height * aspect_ratio
    return int(new_width), int(new_height)


def draw_progress_bar(clip_fps, clip_start, clip_end, video_duration, screen, frame_idx: int, draw_clip: bool, step_timestamps: list[int]):
    """Draw a progress bar at the bottom of the screen."""
    progress_bar_height = 50

    if draw_clip:
        clip_progress_percent = frame_idx / (clip_fps * (clip_end - clip_start))
        clip_progress_bar_width = int(screen.get_width() * clip_progress_percent)

        clip_progress_bar_rect = pygame.Rect(0, screen.get_height() - progress_bar_height, clip_progress_bar_width, progress_bar_height / 2)
        pygame.draw.rect(screen, "green", clip_progress_bar_rect)

        full_progress_bar_height = progress_bar_height / 2
    else:
        full_progress_bar_height = progress_bar_height

    full_progress_percent = ((clip_fps * clip_start) + frame_idx) / (clip_fps * video_duration)
    full_progress_bar_width = int(screen.get_width() * full_progress_percent)

    full_progress_bar_rect = pygame.Rect(0, screen.get_height() - full_progress_bar_height, full_progress_bar_width, full_progress_bar_height)
    pygame.draw.rect(screen, "red", full_progress_bar_rect)

    for step in step_timestamps:
        step_percent = step / video_duration
        pygame.draw.rect(screen, "white", pygame.Rect(step_percent * screen.get_width(), screen.get_height() - full_progress_bar_height, 1, full_progress_bar_height))


def draw_recording_circle(screen):
    """Draw a red circle near the upper-left corner of the frame."""
    pygame.draw.circle(screen, "red", (75, 75), 50)

#
# Main
#

def play_clip(screen, clip, step_timestamps, ui_func, event_func, repeat):
    """Play a clip with a given UI and event handler. Optionally repeat it infinitely."""
    running = True

    with tempfile.NamedTemporaryFile(suffix=".wav") as audio_file:
        clip.audio.write_audiofile(audio_file.name, codec="pcm_s16le", logger=None)

        pygame.mixer.music.load(audio_file)

        ms_per_frame = 1000 / clip.fps

        # This is used to dynamically correct for any audio/video syncing
        # issues that arise, since we're playing those separately.
        current_video_delay_ms = 0

        while True:
            # This resets the progress bars
            screen.fill((0, 0, 0))

            frame_generator = clip.iter_frames(fps=clip.fps, dtype="uint8")

            # The first frame takes a lot longer to generate. Probably,
            # clip.itertools is being a little too lazy. This is a workaround
            # to generate the first frame eagerly. Otherwise, we'll drop too
            # many frames at the start.
            frame_generator = itertools.chain([next(frame_generator)], frame_generator)

            clock = pygame.time.Clock()
            pygame.mixer.music.play()

            for i, frame in enumerate(frame_generator):
                # Correct for syncing issues by dropping frames or waiting
                if current_video_delay_ms > ms_per_frame:
                    current_video_delay_ms -= ms_per_frame
                    continue
                else:
                    while current_video_delay_ms < -1 * ms_per_frame:
                        current_video_delay_ms += clock.tick(clip.fps)

                frame_surface = pygame.surfarray.make_surface(frame.swapaxes(0, 1))
                screen.blit(frame_surface, (0, 0))
                ui_func(screen, clip, step_timestamps, i)
                pygame.display.flip()

                running, paused, step_delta = event_func(clock, clip, step_timestamps, i, paused=False)
                was_paused = paused
                if paused:
                    pygame.mixer.music.pause()
                while paused and running:
                    running, paused, step_delta = event_func(clock, clip, step_timestamps, i, paused=True)
                    clock.tick(clip.fps)
                if was_paused:
                    pygame.mixer.music.unpause()

                if not running or step_delta is not None:
                    break
                else:
                    current_video_delay_ms += clock.tick(clip.fps) - ms_per_frame

            if not repeat or not running or step_delta in [-1, 1]:
                break

    return running, step_delta


def main():
    """Entrypoint for CLI."""
    data_dir = appdirs.AppDirs("vidsteps", "dhashe").user_data_dir
    os.makedirs(data_dir, mode=0o755, exist_ok=True)
    db_filename = os.path.join(data_dir, "data.sqlite")

    parser = argparse.ArgumentParser(description="Play a video one step at a time.")
    parser.add_argument('-r', '--record', action='store_true', help="Re-record the step timestamps and overwrite any that already exists.")
    parser.add_argument('video_file', help="Video file to use.")
    args = parser.parse_args()

    video_path = os.path.realpath(args.video_file)

    with sqlite3.connect(db_filename) as conn:
        cursor = conn.cursor()
        init_database(cursor)
        if args.record:
            step_timestamps = []
        else:
            step_timestamps = get_timestamps_for_video(cursor, video_path)

    video = moviepy.editor.VideoFileClip(video_path)

    pygame.init()
    pygame.mixer.init()

    display_info = pygame.display.Info()
    screen = pygame.display.set_mode((display_info.current_w * 0.9, display_info.current_h * 0.9 + 50))
    pygame.display.set_caption("vidsteps: " + os.path.basename(video_path))
    video = video.resize(newsize=resize_keep_aspect_ratio(video.size[0], video.size[1], display_info.current_h * 0.9))

    running = True

    if len(step_timestamps) == 0:
        # record steps mode
        def record_ui_func(screen, clip, step_timestamps, frame_idx):
            draw_progress_bar(clip.fps, 0, clip.duration, clip.duration, screen, frame_idx, False, step_timestamps)
            draw_recording_circle(screen)

        def record_event_func(clock, clip, step_timestamps, frame_idx, paused):
            running = True
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    mods = pygame.key.get_mods()
                    if event.key == pygame.K_p:
                        # pause / unpause
                        paused = not paused
                    elif event.key in [pygame.K_SPACE, pygame.K_RETURN]:
                        # record step here
                        step_timestamps.append(frame_idx / clip.fps)
                    elif (event.key == pygame.K_c and (mods & pygame.KMOD_CTRL)) or (event.key == pygame.K_q):
                        # exit
                        running = False

            return running, paused, None

        running, _ = play_clip(screen, video, step_timestamps, record_ui_func, record_event_func, repeat=False)

        with sqlite3.connect(db_filename) as conn:
            cursor = conn.cursor()
            set_timestamps_for_video(cursor, video_path, step_timestamps)

    # play steps mode
    step_idx = 0
    while running and step_idx < len(step_timestamps):

        clip_start = step_timestamps[step_idx]
        clip_end = step_timestamps[step_idx+1] if step_idx+1 < len(step_timestamps) else int(video.duration)

        def play_ui_func(screen, clip, step_timestamps, frame_idx):
            draw_progress_bar(clip.fps, clip_start, clip_end, video.duration, screen, frame_idx, True, step_timestamps)

        def play_event_func(clock, clip, step_timestamps, frame_idx, paused):
            running = True
            step_delta = None
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    mods = pygame.key.get_mods()
                    if event.key in [pygame.K_RETURN, pygame.K_SPACE, pygame.K_RIGHT, pygame.K_j, pygame.K_l]:
                        # next clip
                        step_delta = 1
                    elif event.key in [pygame.K_LEFT, pygame.K_k, pygame.K_h]:
                        # prev clip
                        step_delta = -1
                    elif event.key == pygame.K_p:
                        # pause / unpause
                        paused = not paused
                    elif event.key in [pygame.K_0, pygame.K_BACKSPACE]:
                        # restart current clip
                        step_delta = 0
                    elif (event.key == pygame.K_c and (mods & pygame.KMOD_CTRL)) or (event.key == pygame.K_q):
                        # exit
                        running = False

            return running, paused, step_delta

        try:
            clip = video.subclip(clip_start, clip_end)
        except ValueError:
            running = False
            break

        running, step_delta = play_clip(screen, clip, step_timestamps, play_ui_func, play_event_func, repeat=True)
        step_idx += step_delta or 0
        step_idx = max(step_idx, 0)

    pygame.quit()


if __name__ == "__main__":
    main()
