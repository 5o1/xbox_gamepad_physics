"""Internal contact count shared with checkout experiments."""
def internal_contact_pairs(scene, articulation):
    links = set(articulation.get_links())
    return sum(1 for contact in scene.get_contacts() if all(body in links for body in contact.bodies))
