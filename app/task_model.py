import datetime

from sqlalchemy.ext.hybrid import hybrid_property
from app import db
from fuzzywuzzy import process, fuzz

assignments = db.Table('assignments',
    db.Column('task', db.Integer, db.ForeignKey('task.id')),
    db.Column('user', db.Integer, db.ForeignKey('user.id')))

children = db.Table('children',
    db.Column('parent', db.Integer, db.ForeignKey('task.id')),
    db.Column('child', db.Integer, db.ForeignKey('task.id')),
    db.Column('position', db.Integer),
    db.Column('check', db.Integer),
    db.Column('note', db.Integer))

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Unicode)
    done = db.Column(db.Boolean, default=False)
    global_note = db.Column(db.Unicode)
    global_position = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.datetime.now(datetime.timezone.utc))
    updated_at = db.Column(db.DateTime, default=datetime.datetime.now(datetime.timezone.utc))
    score = db.Column(db.Float)
    draft = db.Column(db.Boolean, default=True)
    tasks = db.relationship('Task',
        secondary=children,
        primaryjoin=children.c.parent==id,
        secondaryjoin=children.c.child==id,
        backref=db.backref('parents', lazy='dynamic'),
        lazy='dynamic')
    to = db.relationship('User',
        secondary=assignments,
        backref=db.backref('task', lazy='dynamic'),
        lazy='dynamic')

    @hybrid_property
    def note(self, parent):
        return db.session.execute(children.select()\
            .filter(children.c.parent == parent.id,\
                children.c.child == self.id))\
                    .first()['note']
    
    def set_note(self, parent, note:str):
        db.session.execute(children.update()\
            .filter(children.c.parent == parent.id,\
                children.c.child == self.id)\
                    .values(note = note))
        db.session.commit()

    #TODO parent position

    @hybrid_property
    def position(self, parent):
        return db.session.execute(children.select()\
            .filter(children.c.parent == parent.id,\
                children.c.child == self.id))\
                    .first()['position']
    
    def set_position(self, parent, position:int):
        # get current position
        # get 'task_in_place' in req position
        # set task_in_place to parent = current position
        # set self position to req position
        current_position = self.position
        db.session.execute(children.update()\
            .filter(children.c.parent == parent.id, \
                children.c.child == self.id)\
                    .values(position = position))
        db.session.commit()
    
    def all_done(self):
        return self.progress == 100

    def progress(self):
        done = 0
        for task in self.tasks:
            if task.tasks.count() > 0:
                done += task.progress()
            else:
                done += task.done*100
        return (done/(self.tasks.count()*100))*100
        
    def parent(self, task, depth):
        if not self.parents.first():
            return False
        else:
            for parent in self.parents:
                if not self.parents.filter(Task.parents.any(id=task.id)).first():
                    for parent in self.parents:
                        return parent.parent(task)

    def dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'done': self.done,
            'created_at': self.created_at
        }

    @staticmethod
    def get(id, search, sort, order, task, depth):
        query = Task.query
        if task:
            query = query.filter(Task.parents.any(Task.id==task.id))
            #TODO #maybe# variable depth
        else:
            query = Task.query.except_(query.join(children, children.c.child == Task.id))
        if sort:
                if sort == 'alpha':
                    if order == 'asc':
                        return query.order_by(Task.name.asc())
                    elif order =='dsc':
                        return query.order_by(Task.name.desc())
                elif sort == 'time':
                    # TODO time sort by created_at
                    if order == 'asc':
                        return query.order_by(Task.updated_at.asc())
                    elif order =='dsc':
                        return query.order_by(Task.updated_at.desc())
        elif search:
            for task in query:
                task.score = fuzz.ratio(task.name, search)
            db.session.commit()
            if order == 'asc':
                return query.order_by(Task.score.asc())
            elif order =='dsc':
                return query.order_by(Task.score.desc())
            else:
                return query.order_by(Task.score.desc())
        else:
            return query.order_by(Task.updated_at.desc())

    @staticmethod
    def fuz(search, sort, fields, id, hidden, tags):
        query = Task.query
        for task in query:
            task.score = 0
            for tag in tags:
                try:
                    task.score += process.extractOne(tag, task.tags)[1]
                except:
                    pass
        db.session.commit()
        query.order_by(Task.score.desc())
        return query

    def toggle(self):
        self.done = not self.done
        db.session.commit()

    def edit(self, dict):
        if not len(dict):
            return
        for field in dict:
            if hasattr(self, field):
                if dict[field]:
                    setattr(self, field, dict[field])
            else:
                # TODO
                print('model does not have passed attribute')
                # app.logger.warning('Task model was passed an attribute it does not have in .edit()')
        self.updated_at = datetime.datetime.now(datetime.timezone.utc)
        db.session.commit()

    def delete(self):
        db.session.delete(self)
        for task in self.tasks:
            task.delete()
        db.session.commit()

    def __init__(self, name, task=None):
        last_position = Task.query.order_by(Task.position.desc()).first().position
        if last_position:
            self.position = last_position + 1
        self.name = name
        if task:
            task.add(self)
        db.session.add(self)
        db.session.commit()

    def is_child(self, task):
        self.tasks.filter(
            children.c.child == task.id).count() > 0

    def add(self, task):
        if not self.is_child(task):
            self.tasks.append(task)
            db.session.commit()
            last_position = db.session.execute(children.select()\
                .filter(children.c.parent == self.id)\
                    .order_by(children.c.position.desc()))\
                        .first()['position']
            if last_position:
                position = last_position + 1
            else:
                position = 1
            task.set_position(self, position)

    def remove(self, task):
        if self.is_child(task):
            self.tasks.remove(task)
            db.session.commit()