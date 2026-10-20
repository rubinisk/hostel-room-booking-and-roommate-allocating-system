# Disjoint Set Union (DSU) for roommate grouping

class DisjointSetUnion:
    def __init__(self):
        self.parent={}
        self.rank={}
        self.size={}

    def make_set(self,x):
        if x not in self.parent:
            self.parent[x]=x
            self.rank[x]=0
            self.size[x]=1

    def find(self,x):
        if x not in self.parent:
            self.make_set(x)
            return x

        # path compression
        if self.parent[x] != x:
            self.parent[x]=self.find(self.parent[x])
        return self.parent[x]

    def union(self,x,y):
        root_x=self.find(x)
        root_y=self.find(y)

        # cycle check (already in same group)
        if root_x == root_y:
            return False

        # union by rank
        if self.rank[root_x] < self.rank[root_y]:
            self.parent[root_x]=root_y
            self.size[root_y]+=self.size[root_x]
        elif self.rank[root_x] > self.rank[root_y]:
            self.parent[root_y]=root_x
            self.size[root_x]+=self.size[root_y]
        else:
            self.parent[root_y]=root_x
            self.size[root_x]+=self.size[root_y]
            self.rank[root_x]+=1

        return True

    def connected(self,x,y):
        return self.find(x) == self.find(y)

    def get_set_size(self,x):
        root=self.find(x)
        return self.size.get(root, 1)

    def can_form_group(self,member_ids,max_group_size=4):
        # max group size check
        if len(member_ids) > max_group_size:
            return False, f"Group size {len(member_ids)} exceeds maximum capacity of {max_group_size}."

        # check if any member is already in another group
        roots=set()
        for m in member_ids:
            r=self.find(m)
            if self.get_set_size(m) > 1 and r not in roots:
                component_members=[k for k in self.parent if self.find(k) == r]
                if any(cm not in member_ids for cm in component_members):
                    return False, f"Student ID {m} is already part of an active confirmed group."
            roots.add(r)

        return True, "Valid group structure."

    def rebuild_from_db(self,active_groups):
        # reset and rebuild from db when someone leaves
        self.parent.clear()
        self.rank.clear()
        self.size.clear()

        for grp in active_groups:
            members=grp.get('member_ids', [])
            if not members:
                continue
            leader=members[0]
            self.make_set(leader)
            for m in members[1:]:
                self.make_set(m)
                self.union(leader, m)
