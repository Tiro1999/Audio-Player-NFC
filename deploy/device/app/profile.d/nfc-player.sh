# shellcheck shell=sh
# Login banner of the NFC player: service states, last log lines, commands.
# Sourced by /etc/profile; prints only in interactive shells, once per session.

nfc_player_banner() {
    echo ""
    echo "NFC player"
    for nfc_player_unit in nfc-player nfc-player-receiver nfc-player-bluetooth; do
        if [ -f "/etc/systemd/system/$nfc_player_unit.service" ]; then
            printf '  %-22s %s\n' "$nfc_player_unit" "$(systemctl is-active "$nfc_player_unit" 2>/dev/null)"
        fi
    done
    echo ""
    echo "  Last log lines:"
    journalctl -n 5 -o cat -u nfc-player --no-pager 2>/dev/null | sed 's/^/    /'
    nfc_player_commands=""
    for nfc_player_command in nfc-log nfc-status nfc-restart nfc-test nfc-wifi nfc-bt; do
        if command -v "$nfc_player_command" >/dev/null 2>&1; then
            nfc_player_commands="$nfc_player_commands $nfc_player_command"
        fi
    done
    echo ""
    echo "  Commands:$nfc_player_commands"
    echo ""
}

case "$-" in
    *i*)
        if [ -z "${NFC_PLAYER_BANNER_SHOWN:-}" ]; then
            NFC_PLAYER_BANNER_SHOWN=1
            export NFC_PLAYER_BANNER_SHOWN
            nfc_player_banner
        fi
        ;;
esac
unset -f nfc_player_banner
unset nfc_player_unit nfc_player_command nfc_player_commands
