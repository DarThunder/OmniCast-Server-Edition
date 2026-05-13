{
  description = "Develop of this shit lol";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
    in
    {
      devShells.${system}.default = pkgs.mkShell {
        nativeBuildInputs = with pkgs; [
          yt-dlp
          (python3.withPackages (ps: [
            ps.fastapi
            ps.uvicorn
            ps.zeroconf
            ps.aiofiles
          ]))
          ytdl-sub
        ];

        shellHook = ''
          echo "Hello World!"
        '';
      };
    };
}