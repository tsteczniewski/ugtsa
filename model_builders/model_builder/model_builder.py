import tensorflow as tf


def add_to_collection(name, tensor):
    collection = '{}/{}'.format(tf.get_variable_scope().name, name)
    print('- {}'.format(collection))
    tf.add_to_collection(collection, tensor)


def placeholder(dtype, shape=None, name=None):
    result = tf.placeholder(dtype, shape, name)
    add_to_collection(name, result)
    return result


class Model:
    def __init__(self):
        self.model = self.model_tail = \
            placeholder(tf.float32, name='model')
        self.model_initializers = []
        self.variables = {}

        self.seed = self.seed_tail = \
            placeholder(tf.int64, name='seed')
        self.seed_size = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        model_initializer = tf.Variable(
            tf.concat(self.model_initializers, 0) \
            if self.model_initializers \
            else tf.zeros((0,)), name='model_initializer')
        add_to_collection('model_initializer', model_initializer)

        model_initializer_setter_input = placeholder(
            tf.float32, shape=model_initializer.get_shape(),
            name='model_initializer_setter_input')
        add_to_collection('model_initializer_setter', tf.assign(
            model_initializer, model_initializer_setter_input))


        seed_size = tf.Variable(
            self.seed_size, dtype=tf.int32, name='seed_size')
        add_to_collection('seed_size', seed_size)
        add_to_collection(
            'seed_gradient', tf.zeros((self.seed_size,), dtype=tf.int64))

    def get_variable(self, initializer, name, reuse=False):
        name = '{}/{}'.format(tf.get_variable_scope().name, name)

        if name not in self.variables:
            flattened_initializer = \
                tf.reshape(initializer, shape=(-1,))
            flattened_size = flattened_initializer.get_shape()[0].value
            self.model_initializers += [flattened_initializer]
            flattened_variable, self.model_tail = tf.split(
                self.model_tail, (flattened_size, -1), 0, num=2)
            self.variables[name] = tf.reshape(
                flattened_variable, initializer.get_shape(), name=name)
            return self.variables[name]
        elif reuse:
            return self.variables[name]
        else:
            raise ValueError(
                'get_variable: variable {} already exists'.format(name))

    def get_seed(self):
        self.seed_size += 1
        seed, self.seed_tail = tf.split(self.seed_tail, (1, -1), 0, num=2)
        return seed

    def size(self):
        return sum([model_initializer.shape[0].value
                    for model_initializer in self.model_initializers])


class ModelBuilder(object):
    def __init__(self, variable_scope, player_count, worker_count,
                 statistic_size, update_size, game_state_board_shape,
                 game_state_statistic_size, update_statistic_size):
        self.variable_scope = variable_scope
        self.player_count = player_count
        self.worker_count = worker_count
        self.statistic_size = statistic_size
        self.update_size = update_size
        self.game_state_board_shape = game_state_board_shape
        self.game_state_statistic_size = game_state_statistic_size
        self.update_statistic_size = update_statistic_size

    def _empty_statistic_transformation(
            self, model, game_state_board, game_state_statistic):
        raise NotImplementedError

    def _move_rate_transformation(
            self, model, parent_statistic, child_statistic):
        raise NotImplementedError

    def _game_state_as_update_transformation(self, model, update_statistic):
        raise NotImplementedError

    def _updated_statistic_transformation(
            self, model, statistic, update_count, updates):
        raise NotImplementedError

    def _updated_update_transformation(self, model, update, statistic):
        raise NotImplementedError

    def _cost_function_transformation(
            self, predicted_move_rates, real_move_rates,
            empty_statistic_model, move_rate_model,
            game_state_as_update_model, updated_statistic_model,
            updated_update_model):
        raise NotImplementedError

    def __build_empty_statistic_graph(self):
        print('empty_statistic')
        with tf.variable_scope('empty_statistic'):
            with Model() as model:
                game_state_board = placeholder(
                    tf.float32,
                    [None,
                     self.game_state_board_shape[0],
                     self.game_state_board_shape[1]],
                    name='game_state_board')
                game_state_statistic = placeholder(
                    tf.float32,
                    [None, self.game_state_statistic_size],
                    name='game_state_statistic')

                with tf.variable_scope('transformation'):
                    signal = self._empty_statistic_transformation(
                        model, game_state_board, game_state_statistic)

                output = tf.identity(signal, name='output')
                output_gradient = placeholder(
                    tf.float32, [None, self.statistic_size],
                    name='output_gradient')
                model_gradient, game_state_board_gradient, \
                    game_state_statistic_gradient = tf.gradients(
                        output,
                        [model.model, game_state_board, game_state_statistic],
                        grad_ys=output_gradient)

                for name in ['output',
                             'model_gradient',
                             'game_state_board_gradient',
                             'game_state_statistic_gradient']:
                    add_to_collection(name, locals()[name])

                self.empty_statistic_model_size = model.size()

    def __build_move_rate_graph(self):
        print('move_rate')
        with tf.variable_scope('move_rate'):
            with Model() as model:
                parent_statistic = placeholder(
                    tf.float32,
                    [None, self.statistic_size],
                    name='parent_statistic')
                child_statistic = placeholder(
                    tf.float32,
                    [None, self.statistic_size],
                    name='child_statistic')

                with tf.variable_scope('transformation'):
                    signal = self._move_rate_transformation(
                        model, parent_statistic, child_statistic)

                output = tf.identity(signal, name='output')
                output_gradient = placeholder(
                    tf.float32,
                    [None, self.player_count],
                    name='output_gradient')
                model_gradient, parent_statistic_gradient, \
                    child_statistic_gradient = tf.gradients(
                        output,
                        [model.model, parent_statistic, child_statistic],
                        grad_ys=output_gradient)

                for name in ['output',
                             'model_gradient',
                             'parent_statistic_gradient',
                             'child_statistic_gradient']:
                    add_to_collection(name, locals()[name])

                self.move_rate_model_size = model.size()

    def __build_game_state_as_update_graph(self):
        print('game_state_as_update')
        with tf.variable_scope('game_state_as_update'):
            with Model() as model:
                update_statistic = placeholder(
                    tf.float32,
                    [None, self.update_statistic_size],
                    name='update_statistic')

                with tf.variable_scope('transformation'):
                    signal = self._game_state_as_update_transformation(
                        model, update_statistic)

                output = tf.identity(signal, name='output')
                output_gradient = placeholder(
                    tf.float32,
                    [None, self.update_size],
                    name='output_gradient')
                model_gradient, update_statistic_gradient = tf.gradients(
                    output, [model.model, update_statistic],
                    grad_ys=output_gradient)

                for name in ['output',
                             'model_gradient',
                             'update_statistic_gradient']:
                    add_to_collection(name, locals()[name])

                self.game_state_as_update_model_size = model.size()

    def __build_updated_statistic_graph(self):
        print('updated_statistic')
        with tf.variable_scope('updated_statistic'):
            with Model() as model:
                statistic = placeholder(
                    tf.float32,
                    [None, self.statistic_size],
                    name='statistic')
                update_count = placeholder(
                    tf.int32,
                    [None],
                    name='update_count')
                updates = placeholder(
                    tf.float32,
                    [None, self.update_size * self.worker_count],
                    name='updates')

                with tf.variable_scope('transformation'):
                    signal = self._updated_statistic_transformation(
                        model, statistic, update_count, updates)

                output = tf.identity(signal, name='output')
                output_gradient = placeholder(
                    tf.float32,
                    [None, self.statistic_size],
                    name='output_gradient')
                model_gradient, statistic_gradient, updates_gradient = \
                    tf.gradients(
                        output,
                        [model.model, statistic, updates],
                        grad_ys=output_gradient)

                update_count_gradient = tf.zeros(
                    tf.shape(update_count), dtype=tf.int32)

                for name in ['output',
                             'model_gradient',
                             'statistic_gradient',
                             'update_count_gradient',
                             'updates_gradient']:
                    add_to_collection(name, locals()[name])

                self.updated_statistic_model_size = model.size()

    def __build_updated_update_graph(self):
        print('updated_update')
        with tf.variable_scope('updated_update'):
            with Model() as model:
                update = placeholder(
                    tf.float32,
                    [None, self.update_size],
                    name='update')
                statistic = placeholder(
                    tf.float32,
                    [None, self.statistic_size],
                    name='statistic')

                with tf.variable_scope('transformation'):
                    signal = self._updated_update_transformation(
                        model, update, statistic)

                output = tf.identity(signal, name='output')
                output_gradient = placeholder(
                    tf.float32,
                    [None, self.update_size],
                    name='output_gradient')
                model_gradient, statistic_gradient, \
                    update_gradient = tf.gradients(
                        output, [model.model, statistic, update],
                        grad_ys=output_gradient)

                for name in ['output',
                             'model_gradient',
                             'statistic_gradient',
                             'update_gradient']:
                    add_to_collection(name, locals()[name])

                self.updated_update_model_size = model.size()

    def __build_cost_function_graph(self):
        print('cost_function')
        with tf.variable_scope('cost_function'):
            predicted_move_rates = placeholder(
                tf.float32,
                [None, self.player_count],
                name='predicted_move_rates')
            real_move_rates = placeholder(
                tf.float32,
                [None, self.player_count],
                name='real_move_rates')

            empty_statistic_model = placeholder(
                tf.float32,
                [self.empty_statistic_model_size],
                name='empty_statistic_model')
            move_rate_model = placeholder(
                tf.float32,
                [self.move_rate_model_size],
                name='move_rate_model')
            game_state_as_update_model = placeholder(
                tf.float32,
                [self.game_state_as_update_model_size],
                name='game_state_as_update_model')
            updated_statistic_model = placeholder(
                tf.float32,
                [self.updated_statistic_model_size],
                name='updated_statistic_model')
            updated_update_model = placeholder(
                tf.float32,
                [self.updated_update_model_size],
                name='updated_update_model')

            with tf.variable_scope('transformation'):
                signal = self._cost_function_transformation(
                    predicted_move_rates, real_move_rates,
                    empty_statistic_model, move_rate_model,
                    game_state_as_update_model, updated_statistic_model,
                    updated_update_model)

            output = tf.identity(signal, 'output')

            predicted_move_rates_gradient, empty_statistic_model_gradient, \
                move_rate_model_gradient, \
                game_state_as_update_model_gradient, \
                updated_statistic_model_gradient, \
                updated_update_model_gradient = tf.gradients(
                    output,
                    [predicted_move_rates, empty_statistic_model,
                     move_rate_model,
                     game_state_as_update_model,
                     updated_statistic_model,
                     updated_update_model])

            for name in ['output',
                         'predicted_move_rates_gradient',
                         'empty_statistic_model_gradient',
                         'move_rate_model_gradient',
                         'game_state_as_update_model_gradient',
                         'updated_statistic_model_gradient',
                         'updated_update_model_gradient']:
                add_to_collection(name, locals()[name])

    def build(self):
        with tf.variable_scope(self.variable_scope):
            with tf.variable_scope('settings'):
                self.training = placeholder(tf.bool, name='training')
                add_to_collection(
                    'training_gradient', tf.constant(False, dtype=tf.bool))

            self.__build_empty_statistic_graph()
            self.__build_move_rate_graph()
            self.__build_game_state_as_update_graph()
            self.__build_updated_statistic_graph()
            self.__build_updated_update_graph()
            self.__build_cost_function_graph()
