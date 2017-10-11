#! /usr/bin/env python

"""
mp3bot ~ cogs/player/player.py
Discord mp3 player classes

Copyright (c) 2017 Joshua Butt
"""

import asyncio

from glob import glob
from random import shuffle
from re import findall

import discord
from discord.ext import commands

import pafy

from .config import *
from .mp3file import Mp3File


class Playlist:
    """mp3 playlist object"""
    def __init__(self, log, *, playlist_directory=None, cache_length=None):

        self.log = log
        self.playlist_directory = playlist_directory or DEFAULT_PLAYLIST_DIRECTORY

        self.tracks = self._get_tracks
        self.requests = list()
        self.playlist = list(self._get_new_track for track in range(cache_length or DEFAULT_CACHE_LENGTH))

    @property
    def _get_tracks(self):
        """Returns a list of mp3 files in the playlist directory"""
        files = glob(self.playlist_directory + "/*.mp3")
        shuffle(files)
        return files
    
    @property
    def _get_new_track(self):
        """Retruns the next item in the playlist as a :class:Mp3File"""
        try:
            return Mp3File(self.tracks.pop(0), self.log)
        except IndexError:
            self.tracks = self._get_tracks
            return self._get_new_track

    @property 
    def queue(self):
        """Returns the next 10 items in the playlist queue"""
        return (self.requests + self.playlist)[:10]

    @property
    def next_track(self):
        """Returns the next track"""
        if self.requests:
            return self.requests.pop(0)
        self.playlist.append(self._get_new_track)
        return self.playlist.pop(0)

    def add_request(self, request):
        """Adds the requested song to the playlist"""
        self.requests.append(request)


class Session:
    """Discord MP3Player session"""
    def __init__(self, bot, voice, log_channel, playlist, *, permissions=None):
        
        self.bot = bot
        self.voice = voice

        self.log_channel = log_channel
        self.playlist = playlist
        self.permissions = permissions or dict()

        self.is_playing = True
        
        self.skip_requests = list()
        self.volume = DEFAULT_VOLUME

        self.play_next_song = asyncio.Event()
        self.player = self.bot.loop.create_task(self._player_task())

    @property
    def listeners(self):
        """Returns the list of current listeners"""
        return list(filter(self.voice.guild.me.__ne__, [member for member in self.voice.channel.members if not member.voice.self_deaf]))

    def _toggle_next(self, error=None):
        """Plays the next song"""
        if error:
            self.bot.log.error(f"Error occured playing track: {error}")
        self.skip_requests = list()
        self.bot.loop.call_soon_threadsafe(self.play_next_song.set)
    
    def change_volume(self, volume):
        """Changes the player's volume"""
        self.volume = volume
        self.voice.source.volume = volume

    def stop(self):
        """Stops the player"""
        self.is_playing = False
        self.voice.stop()

    async def _log_track(self, track):
        """Logs the specified track in the `log_channel`"""
        if isinstance(track, Mp3File):
            embed = discord.Embed(title=track.title, description=f"{track.album} - ({track.date})", colour=0x009688)
            embed.set_author(name=track.artist)
            embed.set_thumbnail(url="attachment://cover.jpg")
            await self.log_channel.send(embed=embed, file=discord.File(track.cover, "cover.jpg"))
        else:
            embed = discord.Embed(title=track.title, description=track.author, colour=0xf44336)
            embed.set_author(name=f"Youtube Video - requested by {track.requester.name}", url=f"https://youtu.be/{track.videoid}", icon_url="attachment://youtube.png")
            embed.set_thumbnail(url=track.bigthumb)
            await self.log_channel.send(embed=embed, file=discord.File(open(YOUTUBE_LOGO_FILE, 'rb'), "youtube.png"))

    async def _play_track(self, track):
        """Plays the specified track"""
        await self._log_track(track)
        if isinstance(track, Mp3File):
            player = discord.FFmpegPCMAudio(track.file)
        else:
            player = discord.FFmpegPCMAudio(track.getbestaudio().url, options="-bufsize 7680k")

        player = discord.PCMVolumeTransformer(player, self.volume)
        self.voice.play(source=player, after=self._toggle_next)

    async def check_voice_state(self):
        """Checks wether the player should be paused or resumed"""
        listeners = self.listeners
        if len(listeners) != 0 and not self.voice.is_playing():
            self.voice.resume()
        elif len(listeners) == 0 and self.voice.is_playing():
            self.voice.pause()

    async def _player_task(self):
        """Player's asyncio loop"""
        while self.is_playing:
            self.play_next_song.clear()
            await self._play_track(self.playlist.next_track)
            await self.check_voice_state()
            await self.play_next_song.wait()
        await self.voice.disconnect()