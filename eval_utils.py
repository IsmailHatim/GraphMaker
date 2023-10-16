import dgl
import dgl.function as fn
import networkx as nx
import torch

def get_triangle_count(nx_g):
    triangle_count = sum(nx.triangles(nx.to_undirected(nx_g)).values()) / 3
    return triangle_count

def linkx_homophily(graph, y):
    r"""Homophily measure from `Large Scale Learning on Non-Homophilous Graphs:
    New Benchmarks and Strong Simple Methods
    <https://arxiv.org/abs/2110.14446>`__

    Mathematically it is defined as follows:

    .. math::
      \frac{1}{C-1} \sum_{k=1}^{C} \max \left(0, \frac{\sum_{v\in C_k}|\{u\in
      \mathcal{N}(v): y_v = y_u \}|}{\sum_{v\in C_k}|\mathcal{N}(v)|} -
      \frac{|\mathcal{C}_k|}{|\mathcal{V}|} \right),

    where :math:`C` is the number of node classes, :math:`C_k` is the set of
    nodes that belong to class k, :math:`\mathcal{N}(v)` are the predecessors
    of node :math:`v`, :math:`y_v` is the class of node :math:`v`, and
    :math:`\mathcal{V}` is the set of nodes.

    Parameters
    ----------
    graph : DGLGraph
        The graph.
    y : torch.Tensor
        The node labels, which is a tensor of shape (|V|).

    Returns
    -------
    float
        The homophily value.
    """
    with graph.local_scope():
        # Compute |{u\in N(v): y_v = y_u}| for each node v.
        src, dst = graph.edges()
        # Compute y_v = y_u for all edges.
        graph.edata["same_class"] = (y[src] == y[dst]).float()
        graph.update_all(
            fn.copy_e("same_class", "m"), fn.sum("m", "same_class_deg")
        )

        deg = graph.in_degrees().float()
        num_nodes = graph.num_nodes()
        num_classes = y.max(dim=0).values.item() + 1

        value = torch.tensor(0.0).to(graph.device)
        for k in range(num_classes):
            # Get the nodes that belong to class k.
            class_mask = y == k
            same_class_deg_k = graph.ndata["same_class_deg"][class_mask].sum()
            deg_k = deg[class_mask].sum()
            num_nodes_k = class_mask.sum()
            value += max(0, same_class_deg_k / deg_k - num_nodes_k / num_nodes)

        return value.item() / (num_classes - 1)

class Evaluator:
    def __init__(self,
                 data_name,
                 dgl_g_real,
                 X_one_hot_3d_real,
                 Y_one_hot_real):
        """
        Parameters
        ----------
        data_name : str
            Name of the dataset.
        dgl_g_real : dgl.DGLGraph
            Real graph.
        X_one_hot_3d_real : torch.Tensor of shape (F, |V|, 2)
            X_one_hot_3d_real[f, :, :] is the one-hot encoding of the f-th node
            attribute in the real graph.
        Y_one_hot_real : torch.Tensor of shape (|V|, C)
            One-hot encoding of the node label in the real graph.
        """
        self.data_name = data_name

        # If the number of edges in a newly added graph exceeds this limit,
        # a subgraph will be used for certain metric computations.
        self.edge_limit = min(dgl_g_real.num_edges(), 20000)

        # Split datasets without a built-in split.
        add_mask = False
        if data_name in ["amazon_photo", "amazon_computer"]:
            add_mask = True
            torch.manual_seed(0)

        self.preprocess_g(dgl_g_real,
                          X_one_hot_3d_real,
                          Y_one_hot_real,
                          add_mask)

    def add_mask_cora(self, dgl_g, Y_one_hot):
        num_nodes = dgl_g.num_nodes()
        train_mask = torch.zeros(num_nodes)
        val_mask = torch.zeros(num_nodes)
        test_mask = torch.zeros(num_nodes)

        # Based on the raw graph
        num_val_nodes = {
            0: 61,
            1: 36,
            2: 78,
            3: 158,
            4: 81,
            5: 57,
            6: 29
        }

        num_test_nodes = {
            0: 130,
            1: 91,
            2: 144,
            3: 319,
            4: 149,
            5: 103,
            6: 64
        }

        num_classes = Y_one_hot.size(-1)
        for y in range(num_classes):
            nodes_y = (Y_one_hot[:, y] == 1.).nonzero().squeeze(-1)
            nid_y = torch.randperm(len(nodes_y))
            nodes_y = nodes_y[nid_y]

            train_mask[nodes_y[:20]] = 1.

            start = 20
            end = start + num_val_nodes[y]
            val_mask[nodes_y[start: end]] = 1.

            start = end
            end = start + num_test_nodes[y]
            test_mask[nodes_y[start: end]] = 1.

        dgl_g.ndata["train_mask"] = train_mask.bool()
        dgl_g.ndata["val_mask"] = val_mask.bool()
        dgl_g.ndata["test_mask"] = test_mask.bool()

        return dgl_g

    def add_mask_citeseer(self, dgl_g, Y_one_hot):
        num_nodes = dgl_g.num_nodes()
        train_mask = torch.zeros(num_nodes)
        val_mask = torch.zeros(num_nodes)
        test_mask = torch.zeros(num_nodes)

        # Based on the raw graph
        num_val_nodes = {
            0: 29,
            1: 86,
            2: 116,
            3: 106,
            4: 94,
            5: 69
        }

        num_test_nodes = {
            0: 77,
            1: 182,
            2: 181,
            3: 231,
            4: 169,
            5: 160
        }

        num_classes = Y_one_hot.size(-1)
        for y in range(num_classes):
            nodes_y = (Y_one_hot[:, y] == 1.).nonzero().squeeze(-1)
            nid_y = torch.randperm(len(nodes_y))
            nodes_y = nodes_y[nid_y]

            train_mask[nodes_y[:20]] = 1.

            start = 20
            end = start + num_val_nodes[y]
            val_mask[nodes_y[start: end]] = 1.

            start = end
            end = start + num_test_nodes[y]
            test_mask[nodes_y[start: end]] = 1.

        dgl_g.ndata["train_mask"] = train_mask.bool()
        dgl_g.ndata["val_mask"] = val_mask.bool()
        dgl_g.ndata["test_mask"] = test_mask.bool()

        return dgl_g

    def add_mask_benchmark(self, dgl_g, Y_one_hot):
        num_nodes = dgl_g.num_nodes()
        train_mask = torch.zeros(num_nodes)
        val_mask = torch.zeros(num_nodes)
        test_mask = torch.zeros(num_nodes)

        num_classes = Y_one_hot.size(-1)
        for y in range(num_classes):
            nodes_y = (Y_one_hot[:, y] == 1.).nonzero().squeeze(-1)
            nid_y = torch.randperm(len(nodes_y))
            nodes_y = nodes_y[nid_y]

            # Based on the raw paper.
            train_mask[nodes_y[:20]] = 1.
            val_mask[nodes_y[20: 50]] = 1.
            test_mask[nodes_y[50:]] = 1.

        dgl_g.ndata["train_mask"] = train_mask.bool()
        dgl_g.ndata["val_mask"] = val_mask.bool()
        dgl_g.ndata["test_mask"] = test_mask.bool()

        return dgl_g

    def add_mask(self, dgl_g, Y_one_hot):
        if self.data_name == "cora":
            return self.add_mask_cora(dgl_g, Y_one_hot)
        elif self.data_name == "citeseer":
            return self.add_mask_citeseer(dgl_g, Y_one_hot)
        elif self.data_name in ["amazon_photo", "amazon_computer"]:
            return self.add_mask_benchmark(dgl_g, Y_one_hot)
        else:
            raise ValueError(f'Unexpected data name: {self.data_name}')

    def sample_subg(self, dgl_g):
        # Sample edge-induced subgraph for costly computation.
        A = dgl_g.adj().to_dense()
        A_upper = torch.triu(A, diagonal=1)
        # (|E|, 2)
        edges = A_upper.nonzero()
        indices = torch.randperm(edges.size(0))[:self.edge_limit // 2]
        src, dst = edges[indices].T
        sub_g = dgl.graph((src, dst), num_nodes=dgl_g.num_nodes())
        sub_g = dgl.to_bidirected(sub_g)

        return sub_g

    def preprocess_g(self,
                     dgl_g,
                     X_one_hot_3d,
                     Y_one_hot,
                     add_mask):
        """
        Parameters
        ----------
        dgl_g : dgl.DGLGraph
            Graph.
        X_one_hot_3d : torch.Tensor of shape (F, |V|, 2)
            X_one_hot_3d[f, :, :] is the one-hot encoding of the f-th node
            attribute in the graph.
        Y_one_hot : torch.Tensor of shape (|V|, C)
            One-hot encoding of the node label in the graph.
        add_mask : bool
            Whether to add a mask to the graph for node classification
            data split.
        """
        if add_mask:
            dgl_g = self.add_mask(dgl_g, Y_one_hot)

        F = X_one_hot_3d.size(0)
        # (|V|, F)
        X = torch.zeros(X_one_hot_3d.size(1), F)
        for f in range(F):
            X[:, f] = X_one_hot_3d[f].argmax(dim=1)

        if dgl_g.num_edges() > self.edge_limit:
            dgl_subg = self.sample_subg(dgl_g)
        else:
            dgl_subg = dgl_g

        nx_g = nx.DiGraph(dgl_subg.cpu().to_networkx())

        triangle_count = get_triangle_count(nx_g)

        Y = Y_one_hot.argmax(dim=-1)
        linkx_A = linkx_homophily(dgl_g, Y)
