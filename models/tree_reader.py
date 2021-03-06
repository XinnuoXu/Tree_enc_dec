from typing import List, Set, Tuple, Dict
import numpy
import torch

def gumbel_softmax_function(scores, tau, top_k):
    top_k = int(top_k)
    gumbels = -torch.empty_like(scores.contiguous()).exponential_().log()
    gumbels = (scores + gumbels) / tau
    y_soft = gumbels.softmax(-1)
    top_k = min(top_k, y_soft.size(1))
    indices = torch.topk(y_soft, dim=-1, k=top_k)[1]
    value = 1 / top_k
    y_hard = torch.zeros_like(scores.contiguous()).scatter_(-1, indices, value)
    ret = y_hard - y_soft.detach() + y_soft
    #ret = (ret == value)
    return ret


def topn_function(scores, mask_block, top_n):
    if top_n >= 1:
        top_n = int(top_n)
        indices = torch.topk(scores, min(scores.size(1), top_n))[1]
        y_hard = torch.zeros_like(scores.contiguous()).scatter_(-1, indices, 1)
    else:
        y_hard = []
        nsent_selection = (mask_block.sum(dim=1) * top_n).int().tolist()
        for b in range(len(nsent_selection)):
            indices = torch.topk(scores[b], nsent_selection[b])[1]
            y_h = torch.zeros_like(scores[b].contiguous()).scatter_(-1, indices, 1)
            y_hard.append(y_h)
        y_hard = torch.stack(y_hard)
    return y_hard


def decode_mst(energy: numpy.ndarray, length: int, has_labels: bool = True) -> Tuple[numpy.ndarray, numpy.ndarray]:
    """
    Note: Counter to typical intuition, this function decodes the _maximum_
    spanning tree.
    Decode the optimal MST tree with the Chu-Liu-Edmonds algorithm for
    maximum spanning arborescences on graphs.
    # Parameters
    energy : `numpy.ndarray`, required.
        A tensor with shape (num_labels, timesteps, timesteps)
        containing the energy of each edge. If has_labels is `False`,
        the tensor should have shape (timesteps, timesteps) instead.
    length : `int`, required.
        The length of this sequence, as the energy may have come
        from a padded batch.
    has_labels : `bool`, optional, (default = `True`)
        Whether the graph has labels or not.
    """
    if has_labels and energy.ndim != 3:
        print ("The dimension of the energy array is not equal to 3.")
        return None, None
    elif not has_labels and energy.ndim != 2:
        print ("The dimension of the energy array is not equal to 2.")
        return None, None
    input_shape = energy.shape
    max_length = input_shape[-1]

    # Our energy matrix might have been batched -
    # here we clip it to contain only non padded tokens.
    if has_labels:
        energy = energy[:, :length, :length]
        # get best label for each edge.
        label_id_matrix = energy.argmax(axis=0)
        energy = energy.max(axis=0)
    else:
        energy = energy[:length, :length]
        label_id_matrix = None
    # get original score matrix
    original_score_matrix = energy
    # initialize score matrix to original score matrix
    score_matrix = numpy.array(original_score_matrix, copy=True)

    old_input = numpy.zeros([length, length], dtype=numpy.int32)
    old_output = numpy.zeros([length, length], dtype=numpy.int32)
    current_nodes = [True for _ in range(length)]
    representatives: List[Set[int]] = []

    for node1 in range(length):
        original_score_matrix[node1, node1] = 0.0
        score_matrix[node1, node1] = 0.0
        representatives.append({node1})

        for node2 in range(node1 + 1, length):
            old_input[node1, node2] = node1
            old_output[node1, node2] = node2

            old_input[node2, node1] = node2
            old_output[node2, node1] = node1

    final_edges: Dict[int, int] = {}

    # The main algorithm operates inplace.
    chu_liu_edmonds(
        length, score_matrix, current_nodes, final_edges, old_input, old_output, representatives
    )

    heads = numpy.zeros([max_length], numpy.int32)
    if has_labels:
        head_type = numpy.ones([max_length], numpy.int32)
    else:
        head_type = None

    for child, parent in final_edges.items():
        heads[child] = parent
        if has_labels:
            head_type[child] = label_id_matrix[parent, child]

    return heads, head_type


def chu_liu_edmonds(
    length: int,
    score_matrix: numpy.ndarray,
    current_nodes: List[bool],
    final_edges: Dict[int, int],
    old_input: numpy.ndarray,
    old_output: numpy.ndarray,
    representatives: List[Set[int]],):
    """
    Applies the chu-liu-edmonds algorithm recursively
    to a graph with edge weights defined by score_matrix.
    Note that this function operates in place, so variables
    will be modified.
    # Parameters
    length : `int`, required.
        The number of nodes.
    score_matrix : `numpy.ndarray`, required.
        The score matrix representing the scores for pairs
        of nodes.
    current_nodes : `List[bool]`, required.
        The nodes which are representatives in the graph.
        A representative at it's most basic represents a node,
        but as the algorithm progresses, individual nodes will
        represent collapsed cycles in the graph.
    final_edges : `Dict[int, int]`, required.
        An empty dictionary which will be populated with the
        nodes which are connected in the maximum spanning tree.
    old_input : `numpy.ndarray`, required.
    old_output : `numpy.ndarray`, required.
    representatives : `List[Set[int]]`, required.
        A list containing the nodes that a particular node
        is representing at this iteration in the graph.
    # Returns
    Nothing - all variables are modified in place.
    """
    # Set the initial graph to be the greedy best one.
    parents = [-1]
    for node1 in range(1, length):
        parents.append(0)
        if current_nodes[node1]:
            max_score = score_matrix[0, node1]
            for node2 in range(1, length):
                if node2 == node1 or not current_nodes[node2]:
                    continue

                new_score = score_matrix[node2, node1]
                if new_score > max_score:
                    max_score = new_score
                    parents[node1] = node2

    # Check if this solution has a cycle.
    has_cycle, cycle = _find_cycle(parents, length, current_nodes)
    # If there are no cycles, find all edges and return.
    if not has_cycle:
        final_edges[0] = -1
        for node in range(1, length):
            if not current_nodes[node]:
                continue

            parent = old_input[parents[node], node]
            child = old_output[parents[node], node]
            final_edges[child] = parent
        return

    # Otherwise, we have a cycle so we need to remove an edge.
    # From here until the recursive call is the contraction stage of the algorithm.
    cycle_weight = 0.0
    # Find the weight of the cycle.
    index = 0
    for node in cycle:
        index += 1
        cycle_weight += score_matrix[parents[node], node]

    # For each node in the graph, find the maximum weight incoming
    # and outgoing edge into the cycle.
    cycle_representative = cycle[0]
    for node in range(length):
        if not current_nodes[node] or node in cycle:
            continue

        in_edge_weight = float("-inf")
        in_edge = -1
        out_edge_weight = float("-inf")
        out_edge = -1

        for node_in_cycle in cycle:
            if score_matrix[node_in_cycle, node] > in_edge_weight:
                in_edge_weight = score_matrix[node_in_cycle, node]
                in_edge = node_in_cycle

            # Add the new edge score to the cycle weight
            # and subtract the edge we're considering removing.
            score = (
                cycle_weight
                + score_matrix[node, node_in_cycle]
                - score_matrix[parents[node_in_cycle], node_in_cycle]
            )

            if score > out_edge_weight:
                out_edge_weight = score
                out_edge = node_in_cycle

        score_matrix[cycle_representative, node] = in_edge_weight
        old_input[cycle_representative, node] = old_input[in_edge, node]
        old_output[cycle_representative, node] = old_output[in_edge, node]

        score_matrix[node, cycle_representative] = out_edge_weight
        old_output[node, cycle_representative] = old_output[node, out_edge]
        old_input[node, cycle_representative] = old_input[node, out_edge]

    # For the next recursive iteration, we want to consider the cycle as a
    # single node. Here we collapse the cycle into the first node in the
    # cycle (first node is arbitrary), set all the other nodes not be
    # considered in the next iteration. We also keep track of which
    # representatives we are considering this iteration because we need
    # them below to check if we're done.
    considered_representatives: List[Set[int]] = []
    for i, node_in_cycle in enumerate(cycle):
        considered_representatives.append(set())
        if i > 0:
            # We need to consider at least one
            # node in the cycle, arbitrarily choose
            # the first.
            current_nodes[node_in_cycle] = False

        for node in representatives[node_in_cycle]:
            considered_representatives[i].add(node)
            if i > 0:
                representatives[cycle_representative].add(node)

    chu_liu_edmonds(
        length, score_matrix, current_nodes, final_edges, old_input, old_output, representatives
    )

    # Expansion stage.
    # check each node in cycle, if one of its representatives
    # is a key in the final_edges, it is the one we need.
    found = False
    key_node = -1
    for i, node in enumerate(cycle):
        for cycle_rep in considered_representatives[i]:
            if cycle_rep in final_edges:
                key_node = node
                found = True
                break
        if found:
            break

    previous = parents[key_node]
    while previous != key_node:
        child = old_output[parents[previous], previous]
        parent = old_input[parents[previous], previous]
        final_edges[child] = parent
        previous = parents[previous]


def _find_cycle(
    parents: List[int], length: int, current_nodes: List[bool]
) -> Tuple[bool, List[int]]:

    added = [False for _ in range(length)]
    added[0] = True
    cycle = set()
    has_cycle = False
    for i in range(1, length):
        if has_cycle:
            break
        # don't redo nodes we've already
        # visited or aren't considering.
        if added[i] or not current_nodes[i]:
            continue
        # Initialize a new possible cycle.
        this_cycle = set()
        this_cycle.add(i)
        added[i] = True
        has_cycle = True
        next_node = i
        while parents[next_node] not in this_cycle:
            next_node = parents[next_node]
            # If we see a node we've already processed,
            # we can stop, because the node we are
            # processing would have been in that cycle.
            if added[next_node]:
                has_cycle = False
                break
            added[next_node] = True
            this_cycle.add(next_node)

        if has_cycle:
            original = next_node
            cycle.add(original)
            next_node = parents[original]
            while next_node != original:
                cycle.add(next_node)
                next_node = parents[next_node]
            break

    return has_cycle, list(cycle)


def tree_building(roots, edges, mask, device):
    edge_prob = edges
    #roots = roots.unsqueeze(1)
    roots = roots.transpose(1, 2)
    new_matrix = torch.cat([roots, edge_prob], dim=1)
    dumy_column = torch.zeros((new_matrix.size(0), new_matrix.size(1), 1)).to(device)
    new_matrix = torch.cat([dumy_column, new_matrix], dim=2)

    batch_size = new_matrix.size(0)
    nsents = (torch.sum(mask, dim=1)+1).tolist()
    matrix_npy = new_matrix.cpu().detach().numpy()

    heads_ret = []
    for eid in range(batch_size):
        matrix = matrix_npy[eid]
        sent_num = nsents[eid]
        heads, _ = decode_mst(matrix, sent_num, has_labels=False)
        heads_ret.append(heads)
        
    return heads_ret


def headlist_to_string(list_input):

    def create_tree_str(cnode, childrens, string_list):
        if cnode not in childrens:
            # leaf
            string_list.append('(SENT-'+str(cnode)+' )')
            height = 1
            return string_list, height
        string_list.append('(SENT-'+str(cnode))
        child_heights = []
        for child in childrens[cnode]:
            string_list, height = create_tree_str(child, childrens, string_list)
            child_heights.append(height)
        height = max(child_heights)+1
        string_list.append(')')
        return string_list, height

    childrens = {}
    root = -1
    for vet in range(len(list_input)):
        head = list_input[vet]
        if head == -1:
            root = vet
            continue
        if head not in childrens:
            childrens[head] = set()
        childrens[head].add(vet)

    string_list = []
    string_list, height = create_tree_str(root, childrens, string_list)
    return string_list, height-1


def tree_to_content_mask(tree, mask_src_sent, mask_tgt_sent):
    device = mask_src_sent.device
    tgt_len = mask_tgt_sent.size(-1)
    cross_attn_mask = []
    for i, alg in enumerate(tree):
        src_sent = mask_src_sent[i]
        tgt_sent = mask_tgt_sent[i]
        # for each sent in tgt
        c_mask = []
        for j, sent_alg in enumerate(alg):
            sent_mask = src_sent[sent_alg].sum(dim=0)
            sent_mask = sent_mask.unsqueeze(0)
            sent_mask = sent_mask.repeat((int(tgt_sent[j].sum()), 1))
            c_mask.append(sent_mask)
        c_mask = torch.cat(c_mask)
        # padding
        mask_padding = torch.zeros((tgt_len-c_mask.size(0), c_mask.size(1)), device=device)
        #print (c_mask.size(), mask_padding.size())
        c_mask = torch.cat([c_mask, mask_padding])
        cross_attn_mask.append(c_mask)
    return torch.stack(cross_attn_mask)


def tree_to_mask_list(tree, mask_src_sent):
    cross_attn_mask = []
    for i, alg in enumerate(tree):
        src_sent = mask_src_sent[i]
        # for each sent in tgt
        c_mask = []
        for j, sent_alg in enumerate(alg):
            sent_mask = src_sent[sent_alg].sum(dim=0)
            c_mask.append(sent_mask)
        cross_attn_mask.append(c_mask)
    return cross_attn_mask


def headlist_to_alignments(headlist, length):

    def find_children(headlist, idx):
        children = numpy.where(headlist == idx)[0]
        grand_children_list = []
        for children_idx in children:
            grand_children_list.append(children_idx)
            grand_children = find_children(headlist, children_idx)
            grand_children_list.extend(grand_children)
        return grand_children_list
            
    roots = numpy.where(headlist == 0)[0]
    sub_trees = []
    for idx in roots:
        if idx >= length:
            break
        grand_children_list = find_children(headlist, idx)
        sub_trees.append(grand_children_list+[idx])

    updated_sub_tress = []
    for sub_tree in sub_trees:
        sub_tree = [int(idx-1) for idx in sorted(sub_tree)]
        updated_sub_tress.append(sub_tree)

    return updated_sub_tress

if __name__ == '__main__':
    root = [[0.1, 0.1, 0.1, 0.1, 0.1, 0.1]]
    adjacency = [[0, 0, 0, 0, 0, 0], [1, 0, 0, 1, 0, 0], [0, 0, 0, 0, 0, 0], [0, 0, 1, 0, 0, 0], [0, 0, 0, 0, 0, 1], [0, 0, 0, 0, 0, 0]]
    root = numpy.array(root)
    adjacency = numpy.array(adjacency)
    matrix = numpy.concatenate((root, adjacency), axis=0)
    row_number = matrix.shape[0]
    dummy_column = numpy.zeros((row_number, 1))
    matrix = numpy.concatenate((dummy_column, matrix), axis=1)
    heads, _ = decode_mst(matrix, row_number-3, has_labels=False)
    sub_trees = headlist_to_alignments(heads, row_number-3)
    print ('Matris:')
    print (matrix)
    print ('Predicted Head:')
    print (heads)
    print ('Predicted alignments:')
    print (sub_trees)

