import argparse
import asyncio
import sys
from datetime import datetime

# Import core modules
from core.agent import AegisAgent
from core.history import HistoryManager
from config.settings import settings

class Colors:
    """Simple ANSI color codes for CLI output formatting."""
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def print_color(text: str, color: str = Colors.ENDC, end: str = '\n'):
    """
    Print text with color.
    
    Args:
        text (str): The text to print.
        color (str): ANSI color code.
        end (str): String appended after the last value, default a newline.
    """
    print(f"{color}{text}{Colors.ENDC}", end=end)

def step_callback(step_info: dict):
    """
    Callback function to handle streaming step updates from the agent.
    
    Args:
        step_info (dict): Dictionary containing information about the current step.
    """
    step_num = step_info.get("step_number", "?")
    status = step_info.get("status", "unknown")
    
    if status == "deciding":
        reasoning = step_info.get("reasoning", "")
        print_color(f"[step {step_num}] {reasoning}", Colors.OKCYAN)
    elif status == "executed":
        action_summary = step_info.get("action_summary", "")
        print_color(f"[step {step_num}] {action_summary}", Colors.OKGREEN)
    elif status == "awaiting_confirmation":
        # The confirmation prompt will be handled separately by the confirmation_handler
        pass
    elif status == "complete":
        msg = step_info.get("message", "Task completed successfully.")
        print_color(f"✅ {msg}", Colors.OKGREEN + Colors.BOLD)
    elif status == "aborted":
        msg = step_info.get("message", "Task was aborted.")
        print_color(f"🚫 {msg}", Colors.WARNING)
    elif status == "timeout":
        msg = step_info.get("message", "Task timed out.")
        print_color(f"⏱️ {msg}", Colors.WARNING)
    elif status == "error":
        msg = step_info.get("message", "An error occurred during task execution.")
        print_color(f"❌ {msg}", Colors.FAIL)

async def confirmation_handler(confirmation_msg: str) -> bool:
    """
    Async confirmation handler that prompts the user for confirmation.
    
    Args:
        confirmation_msg (str): The confirmation message to display.
        
    Returns:
        bool: True if the user confirms, False otherwise.
    """
    print_color(f"⚠️  CONFIRMATION NEEDED: {confirmation_msg} — proceed? [y/N] ", Colors.WARNING, end='')
    
    loop = asyncio.get_event_loop()
    # Run input() in an executor so it doesn't block the asyncio event loop
    user_input = await loop.run_in_executor(None, input)
    user_input = user_input.strip().lower()
    
    return user_input in ('y', 'yes')

async def run_task(args: argparse.Namespace):
    """
    Run a specific task using the AegisAgent.
    
    Args:
        args (argparse.Namespace): Parsed command-line arguments.
    """
    task = args.task
    headless = args.headless
    max_steps = args.max_steps
    
    print_color(f"Starting task: '{task}'", Colors.BOLD)
    print_color(f"Headless mode: {headless} | Max steps: {max_steps}", Colors.OKBLUE)
    print("-" * 60)
    
    agent = AegisAgent()
    agent.add_step_callback(step_callback)
    agent.set_confirmation_handler(confirmation_handler)
    
    try:
        result = await agent.run_task(task, headless=headless, max_steps=max_steps)
        print("-" * 60)
        
        # Display final outcome
        status = result.get('status')
        if status == 'success':
            print_color(f"Result: {result.get('message', 'Success')}", Colors.OKGREEN)
        else:
            print_color(f"Result: {result.get('message', 'Task failed or aborted.')}", Colors.FAIL)
            
    except Exception as e:
        print_color(f"\nExecution failed with an unexpected error: {e}", Colors.FAIL)

async def handle_history(args: argparse.Namespace):
    """
    Handle the 'history' command to list past sessions or show session details.
    
    Args:
        args (argparse.Namespace): Parsed command-line arguments.
    """
    history_manager = HistoryManager()
    await history_manager.init_db()
    
    if args.session_id:
        # Show full step-by-step log of a past session
        actions = await history_manager.get_session_actions(args.session_id)
        summary = await history_manager.get_session_summary(args.session_id)
        
        if not summary:
            print_color(f"Session '{args.session_id}' not found.", Colors.FAIL)
            return
            
        print_color(f"Session ID: {args.session_id}", Colors.BOLD)
        print_color(f"Task: {summary.get('task', 'N/A')}", Colors.OKCYAN)
        print_color(f"Status: {summary.get('status', 'N/A')}", Colors.OKBLUE)
        print("-" * 60)
        
        if not actions:
            print_color("No actions recorded for this session.", Colors.WARNING)
            return
            
        for step in actions:
            step_num = step.get('step_number', '?')
            action_type = step.get('action_type', 'unknown')
            reasoning = step.get('reasoning', '')
            result = step.get('result', '')
            
            print_color(f"Step {step_num} | Action: {action_type}", Colors.BOLD)
            if reasoning:
                print_color(f"  Reasoning: {reasoning}", Colors.ENDC)
            if result:
                print_color(f"  Result: {result}", Colors.OKGREEN)
            print()
    else:
        # List all past sessions
        sessions = await history_manager.list_sessions()
        
        if not sessions:
            print_color("No session history found.", Colors.OKBLUE)
            return
            
        print_color(f"{'Session ID':<38} | {'Task':<40} | {'Status':<15} | {'Created At'}", Colors.BOLD)
        print("-" * 120)
        
        for session in sessions:
            # Truncate session_id if necessary (UUIDs are 36 chars)
            sess_id = session.get('session_id', '')[:36]
            
            # Truncate task description for cleaner table output
            task = session.get('task', '')
            if len(task) > 37:
                task = task[:34] + "..."
                
            status = session.get('status', 'unknown')
            created_at = session.get('created_at', '')
            
            print(f"{sess_id:<38} | {task:<40} | {status:<15} | {created_at}")

def main():
    """
    Main entry point for the Aegis CLI.
    Parses arguments and dispatches commands.
    """
    parser = argparse.ArgumentParser(description="Aegis Autonomous Browser Agent CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    subparsers.required = True
    
    # Subcommand: run
    run_parser = subparsers.add_parser("run", help="Run a task")
    run_parser.add_argument("task", type=str, help="The task description to run")
    
    run_parser.add_argument(
        "--headless", 
        action=argparse.BooleanOptionalAction,
        default=settings.HEADLESS_DEFAULT,
        help="Run browser in headless mode (use --no-headless for visible UI)"
    )
    
    run_parser.add_argument(
        "--max-steps",
        type=int,
        default=settings.MAX_STEPS_DEFAULT,
        help="Maximum number of steps allowed for the task"
    )
    
    # Subcommand: history
    history_parser = subparsers.add_parser("history", help="List past sessions or show session details")
    history_parser.add_argument(
        "session_id", 
        type=str, 
        nargs="?", 
        help="Specific session ID to view full step-by-step details"
    )
    
    args = parser.parse_args()
    
    try:
        if args.command == "run":
            asyncio.run(run_task(args))
        elif args.command == "history":
            asyncio.run(handle_history(args))
    except KeyboardInterrupt:
        print_color("\nAborted by user", Colors.WARNING)
        sys.exit(1)

if __name__ == '__main__':
    main()
