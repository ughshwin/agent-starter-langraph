"""Evaluation harness: run a fixed set of questions through the agent.

Runs each question with a fresh agent (no shared state between questions),
prints the full reasoning trace and final answer, and a short summary at the
end. Used to smoke-test the agent across easy -> brutal multi-hop questions.

    python run_suite.py --model qwen2.5:7b
    python run_suite.py --model qwen2.5:7b --only 10   # run one question
"""

import argparse
import sys
import time

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from agent import ReActAgent

ADDITIONAL_QUESTIONS = [
    # Cultural Inference
    "What is the weight of the Volkswagen car whose name resembles a common mint mouth freshener in India, in anvils?",
    "What is the top speed in furlongs per fortnight of the Indian motorcycle whose name is the Hindi word for king?",
    
    # False Premise Detection
    "What is the boiling point in Kelvin of the element discovered by the founder of Microsoft?",
    "How tall in cubits is the mountain named after the founder of Apple?",
    
    # Recency + Multi-hop
    "What is the combined net worth of the current leaders of the G7 nations, expressed as a percentage of global GDP?",
    "How many Big Macs could you buy with the annual salary of the highest paid athlete in the world right now, in the country where the Big Mac is most expensive today?",
    "What is the market cap of the company that made the first smartphone, divided by the current price of Bitcoin in Japanese Yen?",
    "What is the age difference in days between the current Pope and the current Dalai Lama?",
    
    # Obscure Unit Conversion
    "What is the distance from the birthplace of the inventor of the telephone to the birthplace of the inventor of the internet, in smoots?",
    "What is the weight of the International Space Station in blue whales?",
    "What is the length of the Amazon river in London double decker buses stacked end to end?",
    "What is the surface area of the moon expressed in football pitches?",
    
    # Linguistic and Symbol Inference
    "What is the orbital period in dog years of the planet whose chemical symbol is the same as the abbreviation for a medical doctor?",
    "What is the atomic weight of the element whose symbol on the periodic table is also the two letter country code for Ireland?",
    
    # Compounding Multi-hop
    "What is the GDP of the country where the headquarters of the company that acquired Instagram is located, divided by the population of the capital city of the country that invented the sport played at Wimbledon?",
    "What is the combined height in furlongs of the three tallest buildings in the city where the company with the most Nobel Prize winning employees is headquartered?",
    "What is the number of seconds in the age of the universe divided by the number of transistors in the first commercially available CPU?",
    
    # Ambiguity by Design  
    "What is the net worth of the founder of the company whose logo is a fruit with a bite taken out of it, in the GDP of the poorest country in the world?",
    "What is the population of the city that is home to the most Michelin starred restaurants in the world, divided by the number of strings on the instrument most associated with that city's most famous composer?",
    
    # The Most Evil One
    "What is the number of hot dogs that could be laid end to end along the Great Wall of China, if each hot dog was the length of the average surname in the country that consumes the most hot dogs per capita measured in letters converted to centimetres using A equals 1 B equals 2 and so on?"
]

QUESTIONS = [
    # Original 11
    "What is the current population of Tokyo?",
    "What is 1,847 multiplied by 293, divided by the number of bones in the human body?",
    "Who founded the company that makes the GPU in the MacBook Pro, and what year was that person born?",
    "What is the distance in miles between the capital of the country that won the most recent FIFA World Cup and the headquarters of the company with the highest market cap in the world as of today?",
    "What is the age of the current CEO of NVIDIA divided by the number of planets in our solar system, multiplied by the year the first iPhone was released minus 2000?",
    "What is the population of the city where the headquarters of the company that acquired Twitter is located, divided by the founding year of that company?",
    "What is the capital of the largest country in the world by area and what is its current temperature in Celsius?",
    "Who is the richest person in the world right now and how many days old are they today?",
    "What is the GDP of the country where the inventor of the programming language used to build Instagram was born, divided by the population of the city where Meta's headquarters is located?",
    "What is the combined age of the founders of the three most valuable AI companies in the world as of today, divided by the number of parameters in GPT-4?",
    "What is the age of the actor who played the character whose catchphrase became the name of a Nike campaign, in Martian years?",
    
    # New 20
    *ADDITIONAL_QUESTIONS
]

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="qwen2.5:7b")
    parser.add_argument("--max-iters", type=int, default=15)
    parser.add_argument("--only", type=int, default=None,
                        help="Run only question N (1-based).")
    args = parser.parse_args()

    questions = QUESTIONS
    if args.only is not None:
        questions = [QUESTIONS[args.only - 1]]
        base = args.only
    else:
        base = 1

    agent = ReActAgent(model=args.model, max_iterations=args.max_iters,
                       verbose=True)

    results = []
    for offset, q in enumerate(questions):
        n = base + offset
        print("\n" + "#" * 70)
        print(f"# QUESTION {n}: {q}")
        print("#" * 70)
        start = time.time()
        try:
            answer = agent.run(q)
            status = "ok"
        except Exception as exc:  # a crash is itself a finding
            answer = f"CRASHED: {type(exc).__name__}: {exc}"
            status = "crash"
        elapsed = time.time() - start
        print(f"\n>>> Q{n} ANSWER ({elapsed:.0f}s): {answer}")
        results.append((n, status, elapsed, answer.replace("\n", " ")[:200]))

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for n, status, elapsed, ans in results:
        print(f"Q{n:<2} [{status:<5}] {elapsed:>4.0f}s  {ans}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
