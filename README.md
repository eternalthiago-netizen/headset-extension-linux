# jbl-quantum810

Bateria e controles do headset **JBL Quantum 810 Wireless** (dongle USB `0ecb:2069`) no Linux, com indicador na barra superior do GNOME. Sem o JBL conectado, mostra a bateria de fones Bluetooth via UPower.

## O que faz

- Barra superior: ícone de headset e porcentagem da bateria, laranja em 20% e vermelho em 10%, com notificação.
- Menu: microfone e mix jogo/chat (leitura), cancelamento de ruído, sidetone e desligamento automático (configuráveis), iluminação liga/desliga e cor RGB (incluindo "Verde + Amarelo").
- App GTK `quantum810` e linha de comando:

```bash
quantum810 --status              # JSON com bateria e ajustes
quantum810 --lights toggle
quantum810 --color 00ff00,ffff00
quantum810 --anc off|on|talkthru
quantum810 --sidetone off|low|mid|high
quantum810 --autooff never|30|60|120
```

## Instalação

```bash
./build-deb.sh            # gera dist/jbl-quantum810_1.0.0_all.deb
sudo apt install ./dist/jbl-quantum810_1.0.0_all.deb
gnome-extensions enable jbl-quantum810@local
```

Reinicie o GNOME Shell (X11: Alt+F2, `r`, Enter; Wayland: sair e entrar de novo). O pacote instala a regra udev `70-jbl-quantum810.rules`, que dá acesso ao dongle sem root.

## Notas do protocolo HID

- Comandos de ajuste/iluminação só têm efeito depois de uma rodada de leituras ("arm": `0x68 0x67 0x62 0x5c 0x75 0x49 0x51 0x47 0x4a 0x45`). O script sempre confere por leitura.
- A bateria vem do firmware em passos de 5%.
- **Nunca envie mais de 5 segmentos de cor** no relatório `0x4c`: valores maiores podem travar de vez o controlador da iluminação.
- A regra udev precisa ter número menor que 73 (o `uaccess` é aplicado em `73-seat-late`).
