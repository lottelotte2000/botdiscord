{ pkgs }: {
  deps = [
    pkgs.iproute2
    pkgs.ffmpeg-full
    pkgs.python39
    pkgs.ffmpeg
    pkgs.nodejs
    pkgs.libopus
  ];
}
