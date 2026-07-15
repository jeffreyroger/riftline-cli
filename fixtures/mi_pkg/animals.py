"""Classes demonstrating multiple inheritance ambiguity."""


class Flyer:
    """Base class with move() method."""
    def move(self):
        pass


class Swimmer:
    """Another base class also with move() method."""
    def move(self):
        pass


class Duck(Flyer, Swimmer):
    """Inherits from both Flyer and Swimmer, each with move()."""
    def go(self):
        # This should be flagged UNRESOLVED with reason "ambiguous across multiple base classes"
        # because both Flyer and Swimmer define move()
        self.move()
