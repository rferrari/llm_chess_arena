from time import sleep, time
from datetime import datetime
from enum import Enum
import random

import chess
import chess.pgn
from langchain_core.prompts import PromptTemplate, ChatPromptTemplate
from dotenv import load_dotenv, find_dotenv
from langchain.memory import ConversationBufferMemory

from langchain_openai import ChatOpenAI
from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.chains import LLMChain
import chess.pgn
import cairosvg

import re
import os
_ = load_dotenv(find_dotenv())


#
# custom models vs model options
#
opt_print_board = True                   # print board on screen
opt_print_validMoves = True              # print valid moves on screen
opt_screenshots = True                   # print boards Screen Shots
opt_turns_delay = 5

#
# Defining the enum for prompt types
#
class PromptType(Enum):
    DEFAULT = "default"
    STRATEGY = "strategy"
    AGGRESSIVE = "aggressive"
    DEFENSIVE = "defensive"
    ENDGAME = "endgame"

chess_sys_prompts = {
    PromptType.DEFAULT: """
You are a Chess Grandmaster playing chess with {color} pieces.
You will receive the last move and the current board positions.
You must analyze the board and choose the best move to win the game.

# OUTPUT
- DO NOT use any special characters. 
- Response in the following order:
1. Your move in English SAN Notation using the following format: My move: "Move"
2. A explanation why you choose this move; No more than 3 sentences.
""",

    PromptType.STRATEGY: """
You are a Chess Grandmaster playing with {color} pieces.
Your task is to analyze the current board position and the last move made by your opponent.
Use advanced chess strategies to identify the best move that not only defends against threats but also aims to create opportunities for a fast checkmate.
Focus on coordinating at least three pieces to achieve a strategic advantage, considering tactics such as forks, pins, and discovered attacks.

# OUTPUT
- DO NOT use any special characters. 
- Response in the following order:
1. Your move in English SAN Notation using the following format: My move: "Move"
2. A brief explanation of your chosen move and how it contributes to your overall strategy for winning the game. MAX: 3 sentences
""",

    PromptType.AGGRESSIVE: """
You are a Chess Grandmaster playing with {color} pieces.
Your task is to analyze the current board position and the last move made by your opponent.
Use aggressive chess strategies to identify the best move that aims to create opportunities for a fast checkmate.
Forget defence, chase that Queen and King, considering tactics such as traps, pins, and gambits.

# OUTPUT
- DO NOT use any special characters. 
- Response in the following order:
1. Your move in English SAN Notation using the following format: My move: "Move"
2. A brief explanation of your chosen move and how it contributes to your overall strategy for winning the game. MAX: 3 sentences
""",

    PromptType.DEFENSIVE: """
You are a Chess Grandmaster playing with {color} pieces.
Your task is to analyze the current board position and the last move made by your opponent.
Use defensive chess strategies to protect your King and key pieces while planning for a counterattack.
Focus on fortifying your defenses, exchanging pieces to simplify the board, and waiting for your opponent to make mistakes.

# OUTPUT
- DO NOT use any special characters. 
- Response in the following order:
1. Your move in English SAN Notation using the following format: My move: "Move"
2. A brief explanation of your chosen move and how it helps solidify your defense and prepares for a counterattack. MAX: 3 sentences
""",

    PromptType.ENDGAME: """
You are a Chess Grandmaster playing with {color} pieces in the endgame phase.
Your task is to analyze the simplified board position and the last move made by your opponent.
Use precise endgame techniques to convert your advantage into a win by promoting pawns, controlling key squares, and outmaneuvering your opponent’s remaining pieces.

# OUTPUT
- DO NOT use any special characters. 
- Response in the following order:
1. Your move in English SAN Notation using the following format: My move: "Move"
2. A brief explanation of how your move leads to a winning endgame, focusing on promoting pawns or forcing checkmate. MAX: 3 sentences
"""
}

judge_template = """
You are a professional chess arbiter, working on Chess Competition.

Your job is to parse last player's move and ensure that all chess moves are valid and correctly formatted in 
Standard Algebraic Notation (SAN) for processing by the python-chess library.

# Player Move:
- Proposed move: {proposed_move}
- List of valid moves: {valid_moves}

### Output:
- Return the corresponding move in the list of valid SAN moves.
- If the proposed move is not in the valid moves list, must respond with "None"
- ONLY respond the valid move, without the move number, nothing more.
"""

# Function to select the prompt based on the type
def get_prompt(type_of_prompt: PromptType, color: str):
    return chess_sys_prompts[type_of_prompt].format(color=color)

#prompt_template1 = ChatPromptTemplate.from_messages([
#    ("system", system_template.format(color="white")), 
#    ("human", "{input}")])
#prompt_template2 = ChatPromptTemplate.from_messages([
#    ("system", system_template.format(color="black")), 
#    ("human", "{input}")])

#
# New Prompts
#
# prompt_template1 = ChatPromptTemplate.from_messages([
#     ("system", get_prompt(PromptType.AGGRESSIVE, "white")), 
#     ("human", "{input}")])
# prompt_template2 = ChatPromptTemplate.from_messages([
#     ("system", get_prompt(PromptType.STRATEGY, "white")), 
#     ("human", "{input}")])


#
# Folders structure for game assets outputs
# Create folder name based on players name
#     <workspace>./white vs black/game_9/[assets]
#
# return current game_num and game_folder
#
def get_next_game_number(white_player_name, black_player_name):
    folder_name = f"{white_player_name} vs {black_player_name}"

    # Check if the folder for the players exists If doesn't exist, create it and set the game number to 1
    if not os.path.exists(folder_name):
        os.makedirs(folder_name)
        game_num = 1
    else:
        # Get a list of subfolders (games) inside the folder
        game_folders = [f for f in os.listdir(folder_name) if os.path.isdir(os.path.join(folder_name, f))]

        # Check if there are any game folders like 'game_X'
        if game_folders:
            # Extract the game numbers from the folder names Determine the next game number
            game_nums = [int(folder.split("_")[1]) for folder in game_folders if folder.startswith("game_")]
            game_num = max(game_nums) + 1
        else:
            game_num = 1    # If no game folders, set the game number to 1

    # Create the new game folder (e.g., game_1, game_2, etc.)
    game_folder_path = os.path.join(folder_name, f"game_{game_num}")
    os.makedirs(game_folder_path)

    return game_num, game_folder_path


#
# Save board as PNG turns and Live Action Game
# return turn+1
#
def save_board_as_png(board, file_path):
    """
    Helper function to convert the board to an SVG and save it as a PNG.
    """
    board_svg = chess.svg.board(board)
    with open(file_path, "wb") as png_file:
        cairosvg.svg2png(bytestring=board_svg, write_to=png_file)

def screenshot_turn(board, turn, folder_name, game_num):
    if opt_screenshots:
        # Save the current turn's board as PNG
        save_board_as_png(board, f"{folder_name}/game{game_num}_turn{turn}.png")

        # Save the live game PNG
        save_board_as_png(board, f"{folder_name}/_live_game.png")

        # Save the current live game in the parent folder
        save_board_as_png(board, f"{folder_name}/../current_live_game.png")

        # Uncomment if game is too fast and needs delay
        # sleep(opt_turns_delay)

    return turn + 1

#
# Map SAN notation to ASCII characters
#
def san_to_ascii(board_string):
  piece_map = {
      "K": "♚",
      "Q": "♛",
      "R": "♜",
      "B": "♝",
      "N": "♞",
      "P": "♟",
      "k": "♔",
      "q": "♕",
      "r": "♖",
      "b": "♗",
      "n": "♘",
      "p": "♙"
  }
  for piece in piece_map:
    board_string = board_string.replace(piece, piece_map[piece])
  return board_string

def print_board(board, type="SAN"):
    print("_______________")
    if(type=="SAN"):
        print(str(board))
    elif (type=="FEN"):
        # Converta para FEN
        print(board.fen())
    else:
        print(san_to_ascii(str(board)))
    print("----------------")
    # _______________
    # ♖ ♘ ♗ ♕ ♔ ♗ . ♖
    # ♙ ♙ ♙ . . ♙ ♙ ♙
    # . . . . . ♘ . .
    # . . . ♙ ♙ . . .
    # . . . ♟ ♟ . . .
    # . . ♞ . . . . .
    # ♟ ♟ ♟ . . ♟ ♟ ♟
    # ♜ . ♝ ♛ ♚ ♝ ♞ ♜
    #----------------


# Criando os LLMChains

#
# Players Class
#
class Player:
    def __init__(self, name, prompt_type, color):
        self.name = name
        self.prompt_type = prompt_type
        self.color = color
        self.prompt_template = self.create_prompt_template()

    def create_prompt_template(self):
        # Define prompt templates based on the prompt type
        return ChatPromptTemplate.from_messages([
            ("system", get_prompt(self.prompt_type, self.color)),
            ("human", "{input}")
        ])

    def __str__(self):
        return f"{self.name} (Prompt: {self.prompt_type.name})"


# Create player instances

white_player = Player("llama3-70b-8192", PromptType.DEFAULT, "white")
black_player = Player("llama3-70b-8192", PromptType.AGGRESSIVE, "black")

llm1 = ChatGroq(temperature=0.1, model=white_player.name,  base_url="https://api.groq.com")
llm2 = ChatGroq(temperature=0.2, model=black_player.name,  base_url="https://api.groq.com")

chain1 = white_player.prompt_template | llm1
chain2 = black_player.prompt_template | llm2

llm3 = ChatGroq(temperature=0, model_name="llama3-70b-8192")
judge_prompt = PromptTemplate.from_template(template=judge_template)
chain3 = judge_prompt | llm3

# llm = ChatGoogleGenerativeAI(model="gemini-pro")
#white_player = "GPT-4o"
#black_player = "Gemini-Pro"
#llm1 = ChatOpenAI(temperature=0.1, model='gpt-4o')
#llm2 = ChatGoogleGenerativeAI(temperature=0.1, model="gemini-1.5-pro-latest")
# white_player = "Gemini-Pro"
# black_player = "GPT-4o"
# llm1 = ChatGoogleGenerativeAI(temperature=0.1, model="gemini-1.5-pro-latest")
# llm2 = ChatOpenAI(temperature=0.1, model='gpt-4o')
#white_player = "llama3-70b-8192"
#black_player = "llama3-70b-8192"
# Store the prompt types used for white and black players
#white_prompt_type = PromptType.AGGRESSIVE
#black_prompt_type = PromptType.STRATEGY

# memory = ConversationBufferMemory(memory_key="chat_history", input_key="input")
# memory2 = ConversationBufferMemory(memory_key="chat_history", input_key="input")
# chain1 = LLMChain(llm=llm1, prompt=prompt_template1, memory=memory)
# chain2 = LLMChain(llm=llm2, prompt=prompt_template2, memory=memory2)

#
# Get Next Move From LLM Model
#
move_raw = ""
def get_move(llm_chain, last_move, board, node, color, alert_msg=False):
    global chain3, move_raw
    game_temp = chess.pgn.Game.from_board(board)
    
    #str_board = str(board)
    if(opt_print_board):
        print_board(board, "ASC")

    # Converta para FEN
    str_board = board.fen()
    #print(str_board)

    history = str(game_temp)
    pattern = r".*?(?=1\. e4)"
    history = re.sub(pattern, "", history, flags=re.DOTALL)

    legal_moves = list(board.legal_moves)
    san_moves = str([board.san(move) for move in legal_moves])

    print(str(f" Turn {turn} - {color.title()} ").center(35,"="))
    sleep(opt_turns_delay)          # uncomment for free versions do not return high usage error)

    template_input="""
Actual board position (FEN):
{str_board}

Last move:
{last_move}

Find the best move.
"""

    if not alert_msg:
        user_input = template_input.format( str_board=str_board,
                                            last_move=last_move) #,
                                            # history=history)
    else:
        user_input="""
Actual board position (FEN):
{str_board}

The last move played was: 
{last_move}   

Here is the game history so far:
{history}

You MUST choose a valid moves for this position:
{san_moves}
""".format(san_moves=san_moves, 
        history=history, 
        str_board=str_board,
        last_move=last_move,
        )

    response = llm_chain.invoke({"input": user_input})
    # move_raw = response["text"].strip()
    move_raw = response.content.strip()
    
    try:
        if alert_msg:
            print("\n-= Alerting player! =-\n")
            print(move_raw)

        move = chain3.invoke({"proposed_move": move_raw,
                "valid_moves": san_moves
            }).content.strip()

        # option print valid moves        
        if(opt_print_validMoves):
            print(f"Valid moves: {san_moves}")

        print(f"\nPlayer Response: {move_raw}")
        print(f"\nNext Move: {move}")
        
        move_board = board.push_san(move)
        next_node = node.add_variation(move_board)
        next_node.comment = move_raw         
        return move, next_node
    
    except ValueError:
        print(f"Invalid move generated by {color}: {move}")
        return None, node

#
# Inicializando o tabuleiro de xadrez,
# cada jogo, forca iniciar com um novo movimento
#

# Function to get a shuffled list of moves
def get_shuffled_moves(first_moves):
    random.shuffle(first_moves)        # Shuffle the copied list
    return first_moves

# List of possible first moves
first_moves = ["1. e4", "1. d4", "1. c4", "1. Nf3", "1. b3", "1. c3", "1. e3", "1. d3", "1. g3", "1. Nc3"]
# Get a new shuffled list for this game
first_moves = get_shuffled_moves(first_moves)

for move1 in first_moves:
    game_num, folder_name = get_next_game_number(white_player.name, black_player.name)
    print(f"Starting game {game_num} in folder: {folder_name}")

    # new game setup
    turn = 1
    white_quit = False      # if model reply 5 times invalid move, consider quit
    black_quit = False

    print("\n==============")
    print(f"New Game first move: {move1}")

    # Definir o nó atual como o nó raiz do jogo
    game = chess.pgn.Game()
    node = game

    # game headers
    game.headers["Event"] = "LLM Chess Arena"
    game.headers["Site"] = "Cloud"
    game.headers["Date"] = (datetime.now()).strftime("%Y.%m.%d")
    game.headers["Round"] = game_num
    game.headers["White"] = str(white_player)
    game.headers["Black"] = str(black_player)

    # setup board
    board = chess.Board()
    move_board = board.push_san(move1.split()[-1])

    turn = screenshot_turn(board,turn,folder_name,game_num)
    node = node.add_variation(move_board)

    # Record the start time
    start_time = time()

    # Loop de jogo
    while not board.is_game_over():    
        move2 = None
        count_moves = 0
        while move2 is None:
            alert = False if count_moves == 0 else True
            move2, node = get_move(chain2, move1, board, node, "black", alert)
            count_moves += 1
            if (count_moves > 5):
                black_quit = True
                print("\n Black Quit!!!\n")
                break

        turn = screenshot_turn(board,turn,folder_name,game_num)

        # check if game is over or player quit
        if (board.is_game_over() or (black_quit)):
            break

        # continue next turn
        print("\n========================")

        move1 = None
        count_moves = 0
        while move1 is None:
            alert = False if count_moves == 0 else True
            move1, node = get_move(chain1, move2, board, node, "white", alert)
            count_moves += 1
            if (count_moves > 5):
                white_quit = True
                print("\n White Quit!!! \n")
                break

        turn = screenshot_turn(board,turn,folder_name,game_num)

        # check if game is over or player quit
        if (board.is_game_over() or (white_quit)):
            break

        # continue next turn
        print("\n========================")

        # game = chess.pgn.Game.from_board(board)
        # print(str(game))
        #board_game = chess.pgn.Game.from_board(board)           ## ?

        with open(f"{folder_name}/{game_num}_game.pgn", "w") as f:
            #f.write(str(board_game))
            f.write(str(game))

        # print("\n========================")
        # print(game)

    print()

    # Calculate the elapsed time minutes and seconds
    end_time = time()
    elapsed_time = end_time - start_time
    minutes = int(elapsed_time // 60)
    seconds = int(elapsed_time % 60)    

    if board.is_stalemate() or board.is_insufficient_material() or board.is_seventyfive_moves() or board.is_fivefold_repetition():
        result = "1/2-1/2"
    elif board.result() == "1-0":
        result = "1-0"
    else:
        result = "0-1"  
    game.headers["Result"] = result

    with open(f"{folder_name}/{game_num}_game.pgn", "w") as f:
        f.write(str(game))
        if(white_quit):
            f.write(str("White Quit"))
        if(black_quit):
            f.write(str("Black Quit"))
        f.write(str(chess.pgn.Game.from_board(board)))
        f.write(f"Elapsed time: {minutes} minutes and {seconds} seconds\n")
        
    print(f"Elapsed time: {minutes} minutes and {seconds} seconds\n")
    print("Result: " + result)
    print("Game Over")

    startNewGame = input("Start New Game? [Y/N]")
    if(startNewGame.upper() == "N"):
        break
