// crux — Crux Desktop from a terminal.
//
// Two halves that share one core: `crux server` IS the workbench (workspace,
// agent runtime, web client, gateway) with no window, and everything else is a
// client of that gateway — or of the desktop app's, when one is running here.
mod args;
mod assets;
mod account;
mod auth;
mod client;
mod commands;
mod discovery;
mod link_agent;
mod remote;
mod screens;
mod server;
mod settings;

use args::Args;

const USAGE: &str = "\
crux — Crux Desktop without a window

  crux server [options]              serve the workbench (web UI + API) here
  crux login --gateway U --token T   remember a gateway to talk to
  crux status                        which gateway, which workspace, which access

  crux session ls
  crux session new [--project NAME | --directory DIR] [--title T]
  crux session send <id> <prompt…> [--model provider/model] [--agent A] [--wait]
  crux session show <id> [--last N]  the conversation, or its last N turns
  crux session status <id>           working or idle
  crux session wait <id>             until its current turn ends (whoever started
                                     it), then its answer
  crux session find <words…>         the conversations that mention them
  crux session rename <id> <title…>
  crux session archive|unarchive <id>
  crux session move <id> --project NAME
  crux session abort <id>
  crux session rm <id>

  crux screen ls                     every Screen and what is in it: sessions,
                                     terminals (and the agent in each), with
                                     the ids the other commands take
  crux screen new [SESSION_ID…] [--sessions N] [--terminals N [--run CMD]]
                  [--name NAME] [--project NAME | --directory DIR]
                                     a new Screen, split evenly among its panes
                                     (--sessions starts new conversations;
                                     --run is typed into each new terminal)
  crux screen add <SCREEN> [SESSION_ID | --new | --terminal [--run CMD]]
                                     one more pane, beside the others
  crux screen add --here [SESSION_ID | --new | --terminal [--run CMD]]
                                     one more pane, right of the one you are in
  crux screen show <SCREEN>          bring it up in the desktop window
  crux screen close <SCREEN>         close it (the conversations are kept)
  crux term read <id> [--turns N] [--lines N]
                                     what a terminal is doing: the agent's own
                                     conversation (Claude Code, Codex), or a
                                     shell's recent output
  crux term send <id> <text…> [--wait] [--no-enter] [--timeout S]
                                     type into it (Enter included); --wait
                                     returns the agent's reply
  crux term key <id> <key…>          press keys, for menus and dialogs: up down
                                     left right enter esc tab shift-tab space
                                     backspace ctrl-c ctrl-d, or one character

  crux audit [--account NAME] [--session ID] [--action A] [--since 2026-10-01]
             [--until DATE] [--limit N]
                                     who did what through the gateway (the
                                     desktop's owner only): messages, deletions,
                                     terminal input, sign-ins

  crux project ls
  crux project new <name>
  crux project add <path> [--mode in-place|copy]

  crux worktree create <id> [--agent A] [--prompt P] [--status S] [--comment C]
  crux worktree set [id|current] [--status S] [--comment C] [--display-name N]
  crux worktree current | ps | ls | diff <id> | merge <id> [--verify CMD] | rm <id> | agents

  crux run ls
  crux run log <hash>

  crux fs ls [path]                  browse the workspace
  crux fs get <path> [--output F]    read one file
  crux fs put <file> [--session ID | --directory DIR] [--name N]
                                     put a file into a session's folder

  crux settings [--json]             the desktop's settings and their values
  crux settings set KEY=VALUE… --reason R [--no-wait]
                                     ask the user to change them: one request,
                                     approved in the Crux window
  crux settings status <id>          the user's decision on a request

  crux model                         the default model every turn uses
  crux model ls                      what this machine can actually serve
  crux model set <provider/model>

  crux permission ls [--session ID]  what an agent is waiting to be allowed
  crux permission allow|once|deny <id> [--session ID]
  crux question ls [--session ID]    what an agent asked and is waiting on
  crux question answer <id> <answer…> one per question: an option or your words
  crux question reject <id>          let it go on without an answer
  crux approval                      whether the agent has to ask at all
  crux approval set full|approve     `full` never asks — for unattended machines

  crux auth set <provider> --key K [--model provider/model] [--base-url URL]
                           [--models id,id] [--npm PKG]
                                     provider credentials, LOCAL to this machine
                                     (--models is REQUIRED for your own endpoint:
                                     an id the runtime has no catalog entry for
                                     only loads when it lists its models)
  crux auth ls

  crux account ls                    who can sign in to the web client
  OSD_PASSWORD=… crux account add <name>   add one, or set a new password
  crux account rm <name>

Discovery (multi-agent scientific search)
  crux eval [-m NOTE] [--direction ID] [--tune]
                                     grade the current worktree and record to the ledger
  crux board | direction | claim | release | tree | insight | review | radio
                                     shared epistemic state, claims, lineage, and radio bus
  crux discovery init|start|stop|resume|status|ls|log|validate|doctor|ledger|ui …
                                     create, launch, inspect, and steer discovery runs

Remote servers
  crux remote list
  crux remote status <host>
  crux remote pair <host>
  crux remote exec <host> -- <program> [args…]
  crux remote put <host> <local-file> <remote-path>
  crux remote get <host> <remote-path> <local-file>
  crux discovery <verb> [args…] --on <host>

Server options
  --port N          bind this exact port (default 4098, then any free port)
  --lan             also accept connections from the network (default: loopback)
  --token T         use this token instead of the stored/generated one
  --mode MODE       full (default) or read-only
  --workspace DIR   open on this folder
  --resources DIR   where the bundled skills/plugins live (default: next to crux)
  --state-dir DIR   keep this instance's state (sessions, sidecar, workspace
                    record) under DIR (also: CRUX_STATE_DIR)

Common options
  --gateway URL     the gateway to talk to (else OSD_GATEWAY, the stored login,
                    or a gateway already running on this machine)
  --token TOKEN     its access token (else OSD_TOKEN, or the stored login)
  --json            print the API's own reply, for scripts
";

fn main() {
    let argv: Vec<String> = std::env::args().skip(1).collect();
    discovery::enforce_agent_guard(&argv);
    if discovery::should_route(&argv) {
        if let Err(e) = discovery::run(&argv) {
            fail(&e);
        }
        return;
    }
    if argv.first().is_some_and(|v| v == "link-agent" || v == "remote") {
        let result = if argv[0] == "link-agent" {link_agent::run_link_agent(&argv[1..])} else {remote::run_remote(&argv[1..])};
        if let Err(e) = result {fail(&e);}
        return;
    }
    let args = match Args::parse(argv) {
        Ok(a) => a,
        Err(e) => fail(&e),
    };
    if args.command.is_empty() || args.command == "help" || args.has("help") {
        print!("{USAGE}");
        return;
    }
    let result = match args.command.as_str() {
        "server" | "serve" => server::run(&args),
        "auth" => auth::run(&args),
        "account" => account::run(&args),
        // Internal: the desktop app's terminal host (osd-core termd.rs), which
        // the app starts on its own. Not in USAGE.
        "termd" => termd(&args),
        "version" | "--version" => {
            println!("crux {}", env!("CARGO_PKG_VERSION"));
            Ok(())
        }
        _ => commands::run(&args),
    };
    if let Err(e) = result {
        fail(&e);
    }
}

/// Where `crux` keeps its data and finds its bundled resources. Shared by the
/// server and by `crux auth`, which both work on this machine's own files.
pub fn env(args: &Args) -> Result<osd_core::Env, String> {
    osd_core::Env::headless(
        args.value("resources").map(std::path::PathBuf::from),
        args.value("state-dir").map(std::path::PathBuf::from),
        env!("CARGO_PKG_VERSION").to_string(),
    )
}

fn fail(message: &str) -> ! {
    eprintln!("crux: {message}");
    std::process::exit(1);
}

/// The terminal host. Its own session first, so nothing aimed at the app's
/// terminal or process group (a hangup, a Ctrl-C) reaches the shells it holds.
fn termd(args: &Args) -> Result<(), String> {
    let dir = args.value("dir").ok_or("termd needs --dir")?;
    #[cfg(unix)]
    unsafe {
        libc::setsid();
    }
    osd_core::termd::serve(std::path::Path::new(&dir))
}
