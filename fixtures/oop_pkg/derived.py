from .base import Animal

class Dog(Animal):
    def bark(self):
        self.play()  # self-call to its own method (resolvable)

    def play(self):
        self.eat()   # subclass calling inherited method (resolvable via inheritance)
        self.toy.squeak()  # self.attr.method() case (deliberately unresolved)
