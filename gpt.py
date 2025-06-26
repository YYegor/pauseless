from gpt4all import GPT4All
from telegram import Update

import config

class GPT:
    def __init__(self):
        self.model = GPT4All(model_path=config.GPT_model_path,
                        model_name=config.GPT_model_name,
                        n_threads=config.GPT_n_threads)

    async def get_word_meaning(self, word, series_name, sentence):
        request_input = (f"In this script line '{sentence}' from '{series_name}' TV series give a contextual definition"
                         f" of '{word}' in one short sentence as in a dictionary, with simple words. Do not mention the TV show.")

        with self.model.chat_session():
                response2 = self.model.generate(
                prompt=f"{request_input}",
                temp=config.GPT_temp)
                # print(f"{model.current_chat_session[-1]['content']} \n\n")
                return response2

if __name__ == '__main__':
    m = GPT()
    print (m.get_word_meaning('larynx', 'Severance', "If you breathe on me, "
                                                        "I'll rip your larynx out."))