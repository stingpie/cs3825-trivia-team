import re

## ChatGPT (who arranged the tasks) was really lopsided in it's workload.
## Like, I have four tasks. The first is to SET UP THE ENTIRE BACK END.
## the second is string normalization (this).
## the third is to parse the quiz JSON. That's just a feature of python.
## The fourth is to 'Security Integration" which... I guess is a task?
def normalize(string):
    string = string.strip()
    string = re.sub(' +', " ", string)
    string = string.lower()
    string = re.sub("(<=[0-9]),(<=[0-9])", "", string) ## remove commas from numbers.
    ## Should I remove commas entirely? there's not much point for a short answer.
    ## But maybe a teacher wants the students to perfectly recite a qoute.

    ## I feel like I should normalize more, but any more normalization seems like it 
    ## might defeat the purpose of what a teacher is trying to teach. 

    return string

def same(string1, string2):
    return normalize(string1) == normalize(string2)


